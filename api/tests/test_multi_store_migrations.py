import os
import runpy
import unittest
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


MIGRATIONS = ("022_stores.py", "023_stock_per_store.py", "024_store_documents.py", "025_online_channel.py")
# Every table the migrations reference must exist in the temporary schema so that no
# unqualified statement can resolve through search_path to the shared public schema.
TABLES = (
    "companies", "parties", "accounts", "products", "product_variants", "stock_balances", "stock_movements",
    "invoices", "purchases", "receivables", "receivable_payments", "purchase_payments", "account_transactions",
    "borrowings", "accounting_period_locks", "invoice_sequences", "shop_orders", "checkout_settings",
)
NEW_TABLES = ("stores", "stock_transfers", "document_sequences", "enquiries", "cod_settlements", "cod_settlement_items")


@unittest.skipUnless(os.getenv("TENALI_TEST_DB_CONCURRENCY") == "1",
                     "Set TENALI_TEST_DB_CONCURRENCY=1 to run migrations in a temporary isolated schema")
class MultiStoreMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dotenv import load_dotenv
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        load_dotenv("api/.env")
        from app.core.database import engine

        cls.admin_engine = engine
        cls.schema = "multistore_migration_" + uuid4().hex
        with engine.begin() as connection:
            if connection.execute(text("select to_regclass('public.stores')")).scalar_one():
                raise unittest.SkipTest("Migrations 022-025 are already applied to the shared schema; the pre-apply rehearsal no longer applies")
            quote = connection.dialect.identifier_preparer.quote
            source = connection.execute(text("select current_schema()")).scalar_one()
            connection.exec_driver_sql(f"create schema {quote(cls.schema)}")
            for table in TABLES:
                connection.exec_driver_sql(
                    f"create table {quote(cls.schema)}.{quote(table)} (like {quote(source)}.{quote(table)} including all)"
                )
            # Audit rows for synthetic companies cannot satisfy public.audit_events foreign keys;
            # shadow the audit function inside the temporary schema so triggers bind to a no-op.
            connection.exec_driver_sql(
                f"create function {quote(cls.schema)}.tenali_operational_audit() returns trigger language plpgsql "
                "as $$ begin return null; end $$"
            )
        cls.engine = create_engine(engine.url, poolclass=NullPool,
                                   connect_args={"options": f"-c search_path={cls.schema},public"})

    @classmethod
    def tearDownClass(cls):
        from sqlalchemy import text

        cls.engine.dispose()
        with cls.admin_engine.begin() as connection:
            quote = connection.dialect.identifier_preparer.quote
            for table in reversed(TABLES + NEW_TABLES):
                connection.exec_driver_sql(f"drop table if exists {quote(cls.schema)}.{quote(table)} cascade")
            connection.exec_driver_sql(f"drop function if exists {quote(cls.schema)}.tenali_operational_audit()")
            connection.exec_driver_sql(f"drop function if exists {quote(cls.schema)}.tenali_default_store()")
            connection.exec_driver_sql(f"drop schema {quote(cls.schema)}")
            if connection.execute(text("select 1 from pg_namespace where nspname=:s"), {"s": cls.schema}).first():
                raise RuntimeError("Temporary migration schema was not removed")

    def run_migrations(self, connection):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        versions = Path(__file__).parents[1] / "alembic" / "versions"
        for name in MIGRATIONS:
            module = runpy.run_path(str(versions / name))
            with Operations.context(MigrationContext.configure(connection)):
                module["upgrade"]()

    def test_upgrade_preserves_stock_and_documents(self):
        from sqlalchemy import text
        company, other, product, variant_product, variant, party, invoice = (str(uuid4()) for _ in range(7))
        with self.engine.begin() as db:
            for cid, name in ((company, "Store migration A"), (other, "Store migration B")):
                db.execute(text("insert into companies(id, company_name, address) values(:id, :name, 'Chennai')"),
                           {"id": cid, "name": name})
            db.execute(text("insert into parties(id, company_id, party_type, legal_name) values(:id, :c, 'customer', 'P')"),
                       {"id": party, "c": company})
            for pid, name in ((product, "Base"), (variant_product, "Varianted")):
                db.execute(text("insert into products(id, company_id, name, portal_product_id) values(:id, :c, :n, :n)"),
                           {"id": pid, "c": company, "n": name})
            db.execute(text("insert into product_variants(id, product_id, variant_name) values(:id, :p, 'L')"),
                       {"id": variant, "p": variant_product})
            for qty in ("3", "4"):  # duplicate NULL-variant rows that the old constraint allowed
                db.execute(text("insert into stock_balances(company_id, product_id, variant_id, quantity) values(:c, :p, null, :q)"),
                           {"c": company, "p": product, "q": Decimal(qty)})
            db.execute(text("insert into stock_balances(company_id, product_id, variant_id, quantity) values(:c, :p, :v, 2.5)"),
                       {"c": company, "p": variant_product, "v": variant})
            db.execute(text("""insert into stock_movements(company_id, product_id, variant_id, movement_type, quantity, notes)
                values(:c, :p, null, 'ADJUSTMENT_IN', 7, 'seed')"""), {"c": company, "p": product})
            db.execute(text("""insert into invoices(id, company_id, invoice_number, customer_party_id, subtotal, total)
                values(:id, :c, 'INV-202609-00001', :party, 100, 100)"""), {"id": invoice, "c": company, "party": party})
            db.execute(text("insert into invoice_sequences(company_id, year, month, last_number) values(:c, 2026, 9, 1)"),
                       {"c": company})
            db.execute(text("""insert into shop_orders(company_id, shopper_id, request_key, request_hash, status, items, address,
                subtotal_paise, shipping_paise, total_paise, provider_key_id, credentials, pickup_location)
                values(:c, :s, :k, 'h', 'payment_review', '[]', '{}', 100, 0, 100, 'k', 'c', 'p')"""),
                       {"c": company, "s": str(uuid4()), "k": str(uuid4())})
            self.run_migrations(db)

        with self.engine.connect() as db:
            stores = db.execute(text("select company_id, code, kind, holds_stock, is_default from stores order by company_id")).mappings().all()
            self.assertEqual(sorted((str(s["company_id"]), s["code"], s["kind"], s["holds_stock"], s["is_default"]) for s in stores),
                             sorted([(company, "MAIN", "offline", True, True), (other, "MAIN", "offline", True, True)]))
            main = str(db.execute(text("select id from stores where company_id=:c"), {"c": company}).scalar_one())
            balances = db.execute(text("""select product_id, variant_id, quantity, store_id from stock_balances
                where company_id=:c order by product_id"""), {"c": company}).mappings().all()
            self.assertEqual(len(balances), 2)
            by_product = {str(b["product_id"]): b for b in balances}
            self.assertEqual(by_product[product]["quantity"], Decimal("7.000"))
            self.assertEqual(by_product[variant_product]["quantity"], Decimal("2.500"))
            self.assertTrue(all(str(b["store_id"]) == main for b in balances))
            self.assertEqual(db.execute(text("select count(*) from stock_movements where store_id is null")).scalar_one(), 0)
            with self.assertRaises(Exception):
                with db.begin_nested():
                    db.execute(text("insert into stock_balances(company_id, store_id, product_id, variant_id, quantity) values(:c, :s, :p, null, 1)"),
                               {"c": company, "s": main, "p": product})
            self.assertEqual(str(db.execute(text("select store_id from invoices where id=:id"), {"id": invoice}).scalar_one()), main)
            self.assertIsNone(db.execute(text("select to_regclass(:name)"), {"name": f"{self.schema}.invoice_sequences"}).scalar_one())
            self.assertIsNotNone(db.execute(text("select to_regclass(:name)"), {"name": f"{self.schema}.document_sequences"}).scalar_one())
            self.assertIsNotNone(db.execute(text("select to_regclass('public.invoice_sequences')")).scalar_one(),
                                 "The shared invoice_sequences table must not be touched by the isolated run")
            self.assertEqual(db.execute(text("select status from shop_orders where company_id=:c"), {"c": company}).scalar_one(),
                             "fulfilment_review")
            self.assertEqual(db.execute(text("select count(*) from parties where system_role='online_shopper'")).scalar_one(), 2)
            self.assertEqual(db.execute(text("""select count(*) from pg_constraint where conrelid=cast(:t as regclass)
                and pg_get_constraintdef(oid) like '%TRANSFER_IN%'"""), {"t": f"{self.schema}.stock_movements"}).scalar_one(), 1)
        with self.engine.begin() as db:
            # A receivable inserted without a store inherits its invoice's store through the trigger.
            db.execute(text("""insert into receivables(company_id, invoice_id, party_id, amount_due, status)
                values(:c, :i, :p, 100, 'UNPAID')"""), {"c": company, "i": invoice, "p": party})
            derived = db.execute(text("select store_id from receivables where invoice_id=:i"), {"i": invoice}).scalar_one()
            self.assertEqual(str(derived), main)


if __name__ == "__main__":
    unittest.main()
