import os
import runpy
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException


@unittest.skipUnless(
    os.getenv("TENALI_TEST_DB_CONCURRENCY") == "1",
    "Set TENALI_TEST_DB_CONCURRENCY=1 to use a temporary isolated PostgreSQL schema",
)
class FinanceConcurrencyTests(unittest.TestCase):
    tables = (
        "companies", "parties", "accounts", "stores", "document_sequences", "stock_balances", "stock_movements",
        "stock_transfers", "account_transactions", "invoices",
        "receivables", "receivable_payments", "purchases", "purchase_payments",
        "accounting_period_locks", "posting_requests", "borrowings",
    )

    @classmethod
    def setUpClass(cls):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from dotenv import load_dotenv
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        load_dotenv("api/.env")
        from app.core.database import engine

        cls.admin_engine = engine
        cls.schema = "finance_regression_" + uuid4().hex
        with engine.begin() as connection:
            source_schema = connection.execute(text("select current_schema()")).scalar_one()
            quote = connection.dialect.identifier_preparer.quote
            connection.exec_driver_sql(f"create schema {quote(cls.schema)}")
            for table in cls.tables:
                connection.exec_driver_sql(
                    f"create table {quote(cls.schema)}.{quote(table)} "
                    f"(like {quote(source_schema)}.{quote(table)} including all)"
                )
            # LIKE does not copy triggers; documents need the store-defaulting trigger to satisfy NOT NULL.
            for table in ("invoices", "purchases", "receivables", "receivable_payments", "purchase_payments",
                          "account_transactions", "borrowings"):
                connection.exec_driver_sql(
                    f"create trigger tenali_default_store before insert on {quote(cls.schema)}.{quote(table)} "
                    "for each row execute function public.tenali_default_store()"
                )
        cls.engine = create_engine(
            engine.url, poolclass=NullPool,
            connect_args={"options": f"-c search_path={cls.schema},public"},
        )
        try:
            with cls.engine.begin() as connection:
                connection.exec_driver_sql(
                    "alter table borrowings drop column if exists source_transaction_id"
                )
                quote = connection.dialect.identifier_preparer.quote
                connection.exec_driver_sql(
                    f"drop index if exists {quote(cls.schema)}.{quote('uq_receivables_company_invoice')}"
                )
                versions = Path(__file__).parents[1] / "alembic" / "versions"
                for migration_name in ("020_borrowing_source_links.py", "021_unique_invoice_receivable.py"):
                    migration = runpy.run_path(str(versions / migration_name))
                    with Operations.context(MigrationContext.configure(connection)):
                        migration["upgrade"]()
        except BaseException:
            cls.drop_schema()
            raise

    @classmethod
    def drop_schema(cls):
        from sqlalchemy import text

        cls.engine.dispose()
        with cls.admin_engine.begin() as connection:
            quote = connection.dialect.identifier_preparer.quote
            for table in reversed(cls.tables):
                connection.exec_driver_sql(f"drop table {quote(cls.schema)}.{quote(table)}")
            connection.exec_driver_sql(f"drop schema {quote(cls.schema)}")
            remaining = connection.execute(
                text("select 1 from pg_namespace where nspname = :schema"), {"schema": cls.schema}
            ).scalar_one_or_none()
            if remaining:
                raise RuntimeError("The isolated finance test schema was not removed")

    @classmethod
    def tearDownClass(cls):
        cls.drop_schema()

    def setUp(self):
        from sqlalchemy import text
        from sqlalchemy.orm import Session

        self.company, self.party, self.account = (str(uuid4()) for _ in range(3))
        with Session(self.engine) as db:
            db.execute(text("insert into companies(id, company_name) values(:id, 'Isolated regression')"),
                       {"id": self.company})
            from schema_support import ensure_default_store
            ensure_default_store(db, self.company)
            db.execute(text("""insert into parties(id, company_id, party_type, legal_name)
                values(:id, :company, 'customer_vendor', 'Isolated party')"""),
                {"id": self.party, "company": self.company})
            db.execute(text("""insert into accounts(id, company_id, nickname, account_type, party_id)
                values(:id, :company, 'Isolated bank', 'bank', :party)"""),
                {"id": self.account, "company": self.company, "party": self.party})
            db.commit()

    def session(self):
        from sqlalchemy.orm import Session

        db = Session(self.engine)
        db.info["tenali_managed_schema"] = True
        return db

    def run_race(self, lock_fragment, action, other_action=None):
        from sqlalchemy.orm import Session

        gate = Barrier(2, timeout=45)

        class RacingSession(Session):
            def execute(self, statement, *args, **kwargs):
                sql = " ".join(str(statement).lower().split())
                if lock_fragment in sql and not getattr(self, "_race_waited", False):
                    self._race_waited = True
                    gate.wait()
                return super().execute(statement, *args, **kwargs)

        def worker(task):
            with RacingSession(self.engine) as db:
                db.info["tenali_managed_schema"] = True
                try:
                    task(db)
                    return 201
                except HTTPException as error:
                    db.rollback()
                    return error.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, task) for task in (action, other_action or action)]
            return sorted(future.result(timeout=90) for future in futures)

    def test_simultaneous_collections_and_reversal(self):
        from sqlalchemy import text
        from app.schemas.accounts import TransactionReverseCreate
        from app.schemas.billing import InvoiceCreate
        from app.schemas.collections import ReceivablePaymentCreate
        from app.services.accounts_service import AccountsService
        from app.services.billing_service import BillingService
        from app.services.collections_service import CollectionsService

        with self.session() as db:
            invoice = BillingService(db).create_invoice(
                self.company, InvoiceCreate(customer_party_id=self.party, subtotal=150, amount_received=50,
                                            account_id=self.account, payment_mode="bank",
                                            invoice_date=date(2026, 9, 10))
            )
            rid = str(CollectionsService(db).list_receivables(self.company)["items"][0]["id"])

        def collect(db):
            CollectionsService(db).collect_receivable(
                rid, self.company,
                ReceivablePaymentCreate(amount=75, account_id=self.account, payment_mode="bank",
                                        payment_date=date(2026, 9, 11), idempotency_key=str(uuid4())),
            )

        self.assertEqual(self.run_race("select invoice_id from receivables where", collect), [201, 422])
        with self.session() as db:
            state = db.execute(text("select amount_received, status from receivables where id=:id"),
                               {"id": rid}).mappings().one()
            self.assertEqual((state["amount_received"], state["status"]), (Decimal("125"), "PARTIAL"))
            transaction = str(db.execute(text("""select id from account_transactions
                where company_id=:company and source_type='invoice' and source_id=:invoice"""),
                {"company": self.company, "invoice": invoice["id"]}).scalar_one())

        def reverse(db):
            AccountsService(db).reverse_transaction(
                transaction, self.company, TransactionReverseCreate(transaction_date=date(2026, 9, 12))
            )

        self.assertEqual(self.run_race("select id, customer_party_id, invoice_date, total, status", reverse),
                         [201, 422])
        with self.session() as db:
            amount = db.execute(text("select amount_received from receivables where id=:id"), {"id": rid}).scalar_one()
            self.assertEqual(amount, Decimal("75"))

    def test_simultaneous_purchase_payments(self):
        from sqlalchemy import text
        from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate
        from app.services.purchases_service import PurchasesService

        with self.session() as db:
            purchase = PurchasesService(db).create_purchase(
                self.company, PurchaseCreate(vendor_party_id=self.party, subtotal=150,
                                             purchase_date=date(2026, 9, 10))
            )

        def pay(db):
            PurchasesService(db).add_purchase_payment(
                str(purchase["id"]), self.company,
                PurchasePaymentCreate(amount=100, account_id=self.account, payment_mode="bank",
                                      idempotency_key=str(uuid4()), payment_date=date(2026, 9, 11)),
            )

        self.assertEqual(
            self.run_race("select id, company_id, total, amount_paid, payment_status, status, purchase_date", pay),
            [201, 422],
        )
        with self.session() as db:
            state = db.execute(text("""select amount_paid, (select sum(amount) from purchase_payments
                where purchase_id=p.id and reversed_at is null) as ledger from purchases p where id=:id"""),
                {"id": purchase["id"]}).mappings().one()
            self.assertEqual((state["amount_paid"], state["ledger"]), (Decimal("100"), Decimal("100")))

    def test_collection_key_conflict_across_receivables(self):
        from sqlalchemy import text
        from app.schemas.collections import ReceivableCreate, ReceivablePaymentCreate
        from app.services.collections_service import CollectionsService

        with self.session() as db:
            service = CollectionsService(db)
            ids = [
                str(service.create_receivable(
                    self.company, ReceivableCreate(party_id=self.party, amount_due=100)
                )["id"])
                for _ in range(2)
            ]
        key = str(uuid4())

        def collect(receivable_id):
            def action(db):
                CollectionsService(db).collect_receivable(
                    receivable_id, self.company,
                    ReceivablePaymentCreate(amount=50, account_id=self.account, payment_mode="bank",
                                            idempotency_key=key),
                )
            return action

        self.assertEqual(
            self.run_race("insert into receivable_payments", collect(ids[0]), collect(ids[1])),
            [201, 409],
        )
        with self.session() as db:
            count, total = db.execute(text("""select count(*), coalesce(sum(amount), 0)
                from receivable_payments where company_id=:company and idempotency_key=:key"""),
                {"company": self.company, "key": key}).one()
            received = db.execute(text("""select sum(amount_received) from receivables
                where company_id=:company"""), {"company": self.company}).scalar_one()
            self.assertEqual((count, total, received), (1, Decimal("50"), Decimal("50")))

    def test_purchase_key_conflict_across_documents(self):
        from sqlalchemy import text
        from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate
        from app.services.purchases_service import PurchasesService

        with self.session() as db:
            service = PurchasesService(db)
            ids = [
                str(service.create_purchase(
                    self.company, PurchaseCreate(vendor_party_id=self.party, subtotal=100,
                                                 purchase_date=date(2026, 9, 10))
                )["id"])
                for _ in range(2)
            ]
        key = str(uuid4())

        def pay(purchase_id):
            def action(db):
                PurchasesService(db).add_purchase_payment(
                    purchase_id, self.company,
                    PurchasePaymentCreate(amount=50, account_id=self.account, payment_mode="bank",
                                          idempotency_key=key, payment_date=date(2026, 9, 11)),
                )
            return action

        self.assertEqual(
            self.run_race("insert into purchase_payments", pay(ids[0]), pay(ids[1])),
            [201, 409],
        )
        with self.session() as db:
            count, total = db.execute(text("""select count(*), coalesce(sum(amount), 0)
                from purchase_payments where company_id=:company and idempotency_key=:key"""),
                {"company": self.company, "key": key}).one()
            paid = db.execute(text("select sum(amount_paid) from purchases where company_id=:company"),
                              {"company": self.company}).scalar_one()
            self.assertEqual((count, total, paid), (1, Decimal("50"), Decimal("50")))

    def test_collection_and_initial_reversal_are_serialized(self):
        from sqlalchemy import text
        from app.schemas.accounts import TransactionReverseCreate
        from app.schemas.billing import InvoiceCreate
        from app.schemas.collections import ReceivablePaymentCreate
        from app.services.accounts_service import AccountsService
        from app.services.billing_service import BillingService
        from app.services.collections_service import CollectionsService

        with self.session() as db:
            invoice = BillingService(db).create_invoice(
                self.company, InvoiceCreate(customer_party_id=self.party, subtotal=100, amount_received=50,
                                            account_id=self.account, payment_mode="bank",
                                            invoice_date=date(2026, 9, 10))
            )
            receivable_id = str(CollectionsService(db).list_receivables(self.company)["items"][0]["id"])
            transaction_id = str(db.execute(
                text("select id from account_transactions where source_type='invoice' and source_id=:id"),
                {"id": invoice["id"]},
            ).scalar_one())

        def collect(db):
            CollectionsService(db).collect_receivable(
                receivable_id, self.company,
                ReceivablePaymentCreate(amount=75, account_id=self.account, payment_mode="bank",
                                        payment_date=date(2026, 9, 11), idempotency_key=str(uuid4())),
            )

        def reverse(db):
            AccountsService(db).reverse_transaction(
                transaction_id, self.company, TransactionReverseCreate(transaction_date=date(2026, 9, 12))
            )

        outcome = self.run_race("from invoices", collect, reverse)
        self.assertIn(outcome, ([201, 201], [201, 422]))
        with self.session() as db:
            state = db.execute(text("""select r.amount_received, i.amount_received as invoice_received,
                (select coalesce(sum(p.amount), 0) from receivable_payments p
                 where p.receivable_id=r.id and p.reversed_at is null) as ledger,
                (select count(*) from account_transactions t where t.reversal_of_transaction_id=:transaction) as reversals
                from receivables r join invoices i on i.id=r.invoice_id where r.id=:id"""),
                {"id": receivable_id, "transaction": transaction_id}).mappings().one()
            expected = Decimal("75") if outcome == [201, 201] else Decimal("0")
            self.assertEqual((state["amount_received"], state["invoice_received"], state["ledger"], state["reversals"]),
                             (expected, expected, expected, 1))

    def test_purchase_payment_and_reversal_are_serialized(self):
        from sqlalchemy import text
        from app.schemas.accounts import TransactionReverseCreate
        from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate
        from app.services.accounts_service import AccountsService
        from app.services.purchases_service import PurchasesService

        with self.session() as db:
            purchase = PurchasesService(db).create_purchase(
                self.company, PurchaseCreate(vendor_party_id=self.party, subtotal=100, amount_paid=50,
                                             account_id=self.account, payment_mode="bank",
                                             purchase_date=date(2026, 9, 10))
            )
            transaction_id = str(db.execute(
                text("""select t.id from account_transactions t join purchase_payments p on p.id=t.source_id
                    where t.source_type='purchase_payment' and p.purchase_id=:id"""),
                {"id": purchase["id"]},
            ).scalar_one())

        def pay(db):
            PurchasesService(db).add_purchase_payment(
                str(purchase["id"]), self.company,
                PurchasePaymentCreate(amount=75, account_id=self.account, payment_mode="bank",
                                      idempotency_key=str(uuid4()), payment_date=date(2026, 9, 11)),
            )

        def reverse(db):
            AccountsService(db).reverse_transaction(
                transaction_id, self.company, TransactionReverseCreate(transaction_date=date(2026, 9, 12))
            )

        outcome = self.run_race("from purchases", pay, reverse)
        self.assertIn(outcome, ([201, 201], [201, 422]))
        with self.session() as db:
            state = db.execute(text("""select p.amount_paid,
                (select coalesce(sum(q.amount), 0) from purchase_payments q
                 where q.purchase_id=p.id and q.reversed_at is null) as ledger,
                (select count(*) from account_transactions t where t.reversal_of_transaction_id=:transaction) as reversals
                from purchases p where p.id=:id"""),
                {"id": purchase["id"], "transaction": transaction_id}).mappings().one()
            expected = Decimal("75") if outcome == [201, 201] else Decimal("0")
            self.assertEqual((state["amount_paid"], state["ledger"], state["reversals"]),
                             (expected, expected, 1))

    def test_simultaneous_repayments_are_capped(self):
        from app.schemas.settlements import BorrowingEntryCreate
        from app.services.settlements_service import SettlementsService

        with self.session() as db:
            SettlementsService(db).create_borrowing(
                self.company, BorrowingEntryCreate(party_id=self.party, direction="borrow", amount=150,
                                                   transaction_date=date(2026, 9, 10))
            )

        def repay(db):
            SettlementsService(db).create_borrowing(
                self.company, BorrowingEntryCreate(party_id=self.party, direction="repay", amount=100,
                                                   transaction_date=date(2026, 9, 11))
            )

        self.assertEqual(self.run_race("select id, legal_name from parties where", repay), [201, 422])
        with self.session() as db:
            self.assertEqual(
                SettlementsService(db).summarize_borrowings(self.company)["items"][0]["net_outstanding"],
                Decimal("50"),
            )

    def test_borrowing_dates_caps_and_reversals(self):
        from sqlalchemy import text
        from app.schemas.accounts import TransactionReverseCreate
        from app.schemas.settlements import BorrowingEntryCreate
        from app.services.accounts_service import AccountsService
        from app.services.settlements_service import SettlementsService

        with self.session() as db:
            service = SettlementsService(db)
            borrow = service.create_borrowing(
                self.company, BorrowingEntryCreate(party_id=self.party, direction="borrow", amount=100,
                                                   account_id=self.account, transaction_date=date(2026, 9, 10))
            )
            repayment = service.create_borrowing(
                self.company, BorrowingEntryCreate(party_id=self.party, direction="repay", amount=80,
                                                   account_id=self.account, transaction_date=date(2026, 9, 20))
            )
            with self.assertRaises(HTTPException):
                service.create_borrowing(
                    self.company, BorrowingEntryCreate(party_id=self.party, direction="repay", amount=21,
                                                       transaction_date=date(2026, 9, 15))
                )
            service.create_borrowing(
                self.company, BorrowingEntryCreate(party_id=self.party, direction="repay", amount=20,
                                                   account_id=self.account, transaction_date=date(2026, 9, 15))
            )
            self.assertEqual(service.summarize_borrowings(self.company)["items"][0]["net_outstanding"], 0)
            transactions = {
                str(row["source_id"]): str(row["id"])
                for row in db.execute(text("""select id,source_id from account_transactions
                    where company_id=:company and source_type='borrowing'"""),
                    {"company": self.company}).mappings()
            }
            accounts = AccountsService(db)
            with self.assertRaises(HTTPException):
                accounts.reverse_transaction(
                    transactions[str(borrow["id"])], self.company,
                    TransactionReverseCreate(transaction_date=date(2026, 9, 21)),
                )
            accounts.reverse_transaction(
                transactions[str(repayment["id"])], self.company,
                TransactionReverseCreate(transaction_date=date(2026, 9, 21)),
            )
            self.assertEqual(service.summarize_borrowings(self.company)["items"][0]["net_outstanding"], 80)
            rows = service.list_borrowings(self.company)["items"]
            self.assertTrue(next(row for row in rows if row["id"] == repayment["id"])["is_reversed"])

    def test_business_payment_borrowing_reversal_is_linked(self):
        from app.schemas.accounts import BusinessPaymentCreate, TransactionReverseCreate
        from app.services.accounts_service import AccountsService
        from app.services.settlements_service import SettlementsService

        with self.session() as db:
            accounts = AccountsService(db)
            payment = accounts.create_business_payment(
                self.company, BusinessPaymentCreate(from_account_id=self.account, amount=40, purpose="expense",
                                                    transaction_date=date(2026, 9, 10))
            )
            self.assertEqual(SettlementsService(db).summarize_borrowings(self.company)["items"][0]["net_outstanding"], 40)
            accounts.reverse_transaction(
                str(payment["account_transaction"]["id"]), self.company,
                TransactionReverseCreate(transaction_date=date(2026, 9, 11)),
            )
            self.assertEqual(SettlementsService(db).summarize_borrowings(self.company)["items"], [])
            self.assertTrue(SettlementsService(db).list_borrowings(self.company)["items"][0]["is_reversed"])
