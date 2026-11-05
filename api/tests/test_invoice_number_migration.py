import os
import unittest
from datetime import date
from uuid import uuid4


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only migration tests")
class InvoiceNumberMigrationTests(unittest.TestCase):
    def test_existing_documents_survive_and_new_store_ids_are_stable_under_runtime_role(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from sqlalchemy.orm import Session
        from app.core.database import engine
        from app.schemas.stores import StoreInput
        from app.services.document_numbers import next_document_number
        from app.services.stores_service import StoresService, get_store
        from schema_support import apply_invoice_store_code_migration

        with engine.connect() as connection:
            outer = connection.begin()
            try:
                company, customer, store = (str(uuid4()) for _ in range(3))
                connection.execute(text("insert into companies(id,company_name) values(:id,'Number migration test')"), {"id": company})
                connection.execute(text("""insert into stores(id,company_id,code,name,kind,holds_stock,is_default)
                    values(:id,:company,'MAIN','Main','offline',true,true)"""), {"id": store, "company": company})
                connection.execute(text("""insert into parties(id,company_id,party_type,legal_name)
                    values(:id,:company,'customer','Test')"""), {"id": customer, "company": company})
                connection.execute(text("""insert into invoices(company_id,customer_party_id,invoice_number,subtotal,total)
                    values(:company,:customer,'INV-MAIN-202611-00004',10,10)"""), {"company": company, "customer": customer})
                connection.execute(text("""insert into document_sequences(company_id,store_id,kind,year,month,last_number)
                    values(:company,:store,'invoice',2026,11,4)"""), {"company": company, "store": store})
                apply_invoice_store_code_migration(connection)
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    main = get_store(db, company, store)
                    self.assertEqual(main["invoice_code"], "01")
                    self.assertEqual(next_document_number(db, company, main, "invoice", date(2026, 11, 6)), "I012026110600005")
                    self.assertEqual(next_document_number(db, company, main, "invoice", date(2026, 11, 7)), "I012026110700006")
                    self.assertEqual(next_document_number(db, company, main, "invoice", date(2026, 12, 1)), "I012026120100001")
                    self.assertEqual(db.execute(text("select invoice_number from invoices where company_id=:company"),
                                                {"company": company}).scalar_one(), "INV-MAIN-202611-00004")
                    db.execute(text("select set_config('app.tenant_id',:company,true)"), {"company": company})
                    db.execute(text("set local role tenali_runtime"))
                    service = StoresService(db, company)
                    second = service.create_store(StoreInput(code="MAIN2", name="Second", kind="offline"))
                    self.assertEqual(second["invoice_code"], "02")
                    renamed = service.update_store(str(second["id"]), StoreInput(code="SHOP2", name="Renamed", kind="offline"))
                    self.assertEqual(renamed["invoice_code"], "02")
                    service.set_default(str(second["id"]))
                    self.assertEqual(get_store(db, company, store)["invoice_code"], "01")
                    db.execute(text("reset role"))
                    savepoint = db.begin_nested()
                    with self.assertRaises(DBAPIError) as error:
                        db.execute(text("update stores set invoice_code='ZZ' where id=:store"), {"store": store})
                    self.assertIn("cannot be changed", str(error.exception))
                    savepoint.rollback()
            finally:
                outer.rollback()
