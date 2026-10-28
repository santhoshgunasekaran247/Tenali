import csv
import os
import unittest
from io import StringIO
from uuid import uuid4
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from fastapi import HTTPException
from app.services.gst_reconciliation import reconcile_2b


class GstReconciliationTests(unittest.TestCase):
    def test_match_mismatch_missing_and_duplicates(self):
        db=MagicMock()
        db.execute.return_value.mappings.return_value=[dict(id='x',bill_number='A1',purchase_date=date(2026,9,1),subtotal=Decimal('100'),gst_total=Decimal('18'),gst_number='33ABCDE1234F1Z5')]
        headers='supplier_gstin,invoice_number,invoice_date,taxable_value,cgst,sgst,igst,cess\n'
        record='33ABCDE1234F1Z5,A1,2026-09-01,100,9,9,0,0\n'
        result=reconcile_2b(db,'company',headers+record,date(2026,9,1),date(2026,9,30))
        self.assertEqual(result['counts']['MATCHED'],1)
        self.assertEqual(reconcile_2b(db,'company',headers+record*2,date(2026,9,1),date(2026,9,30))['counts']['DUPLICATE_REVIEW'],1)
        self.assertEqual(reconcile_2b(db,'company',headers+record.replace(',9,9,',',8,8,'),date(2026,9,1),date(2026,9,30))['counts']['MISMATCH'],1)
        self.assertEqual(reconcile_2b(db,'company',headers,date(2026,9,1),date(2026,9,30))['counts']['MISSING_IN_2B'],1)

    def test_invalid_csv_and_period_rejected(self):
        with self.assertRaises(HTTPException):
            reconcile_2b(MagicMock(),'company','wrong,headers',date(2026,9,1),date(2026,9,30))
        with self.assertRaises(HTTPException):
            reconcile_2b(MagicMock(),'company','',date(2026,10,1),date(2026,9,30))


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only completion tests")
class HistoricalAgingTests(unittest.TestCase):
    def test_commerce_stock_and_retry_protection(self):
        from dotenv import load_dotenv
        load_dotenv("api/.env")
        from sqlalchemy import text
        from sqlalchemy.orm import Session
        from fastapi import HTTPException
        from app.core.database import engine
        from app.schemas.accounts import AccountCreate, BusinessPaymentCreate
        from app.schemas.billing import InvoiceCreate
        from app.schemas.inventory import ProductInput, VendorOfferInput, StockAdjustment
        from app.schemas.purchases import PurchaseCreate, PurchaseReceiptConfirm
        from app.schemas.masters import HsnMasterCreate
        from app.services.accounts_service import AccountsService
        from app.services.billing_service import BillingService
        from app.services.inventory_service import InventoryService
        from app.services.masters_service import MastersService
        from app.services.purchases_service import PurchasesService
        with engine.connect() as connection:
            outer=connection.begin()
            db=Session(bind=connection,join_transaction_mode="create_savepoint")
            try:
                company,party=str(uuid4()),str(uuid4())
                db.execute(text("insert into companies(id,company_name,address,gst_number) values(:id,'Commerce regression','Chennai','33ABCDE1234F1Z5')"),{"id":company})
                db.execute(text("insert into parties(id,company_id,party_type,legal_name,address) values(:id,:company,'customer_vendor','Commerce Party','Chennai')"),{"id":party,"company":company})
                MastersService(db).create_hsn(HsnMasterCreate(code="8516",description="Test",gst_rate=18),company)
                inventory=InventoryService(db,company)
                from app.schemas.inventory import InventoryLookupCreate
                brand=inventory.create_lookup('brands','Before rename')
                updated=inventory.update_lookup('brands',str(brand['id']),InventoryLookupCreate(name='After rename',description='Edited',is_active=False))
                self.assertEqual(updated['code'],brand['code'])
                self.assertFalse(updated['is_active'])
                product=inventory.save_product(ProductInput(name="Stocked product",hsn_code="8516",selling_price=100))
                product_id=str(product["id"])
                inventory.save_offer(product_id,VendorOfferInput(vendor_id=party,mrp=150,buying_price=80))
                adjustment=StockAdjustment(direction="IN",quantity=10,notes="Opening fixture",idempotency_key=str(uuid4()))
                inventory.adjust_stock(product_id,adjustment)
                inventory.adjust_stock(product_id,adjustment)
                self.assertEqual(inventory.detail(product_id)["stock_qty"],10)
                purchases=PurchasesService(db)
                purchase_data=dict(vendor_party_id=party,idempotency_key=str(uuid4()),lines=[dict(product_id=product_id,description="selected",hsn="8516",quantity=2,rate=80)])
                purchase=purchases.create_purchase(company,PurchaseCreate(**purchase_data))
                replay=purchases.create_purchase(company,PurchaseCreate(**purchase_data))
                self.assertEqual(str(purchase["id"]),str(replay["id"]))
                for _ in range(2):
                    purchases.confirm_purchase_receipt(str(purchase["id"]),company,PurchaseReceiptConfirm(receipt_type="PRODUCT"))
                self.assertEqual(inventory.detail(product_id)["stock_qty"],12)
                billing=BillingService(db)
                invoice_data=dict(customer_party_id=party,idempotency_key=str(uuid4()),billing_address="Chennai",place_of_supply="33 - Tamil Nadu",
                                  lines=[dict(product_id=product_id,description="selected",hsn="8516",quantity=3,rate=100)])
                invoice=billing.create_invoice(company,InvoiceCreate(**invoice_data))
                replay=billing.create_invoice(company,InvoiceCreate(**invoice_data))
                self.assertEqual(str(invoice["id"]),str(replay["id"]))
                self.assertEqual(inventory.detail(product_id)["stock_qty"],9)
                accounts=AccountsService(db)
                account=accounts.create_account(company,AccountCreate(nickname="Commerce bank",account_type="bank",is_company_account=True))
                payment=BusinessPaymentCreate(from_account_id=account["id"],purpose="expense",amount=10,idempotency_key=str(uuid4()))
                first=accounts.create_business_payment(company,payment)
                second=accounts.create_business_payment(company,payment)
                self.assertEqual(str(first["account_transaction"]["id"]),str(second["account_transaction"]["id"]))
                from app.services.document_cancellation import cancel_document,Cancellation
                for _ in range(2):
                    cancel_document(db,company,"invoice",str(invoice["id"]),Cancellation(reason="Test cancellation"))
                self.assertEqual(inventory.detail(product_id)["stock_qty"],12)
                cancel_document(db,company,"purchase",str(purchase["id"]),Cancellation(reason="Test return to supplier"))
                self.assertEqual(inventory.detail(product_id)["stock_qty"],10)
                before=db.execute(text("select count(*) from invoices where company_id=:company"),{"company":company}).scalar_one()
                invoice_data["idempotency_key"]=str(uuid4())
                invoice_data["lines"][0]["quantity"]=100
                with self.assertRaises(HTTPException):
                    billing.create_invoice(company,InvoiceCreate(**invoice_data))
                db.rollback()
                self.assertEqual(inventory.detail(product_id)["stock_qty"],10)
                self.assertEqual(db.execute(text("select count(*) from invoices where company_id=:company"),{"company":company}).scalar_one(),before)
                self.assertGreater(db.execute(text("select count(*) from audit_events where company_id=:company"),{"company":company}).scalar_one(),0)
            finally:
                db.close()
                outer.rollback()

    def test_settlement_and_reversal_respect_cutoff(self):
        from dotenv import load_dotenv
        load_dotenv("api/.env")
        from datetime import date
        from sqlalchemy import text
        from sqlalchemy.orm import Session
        from app.core.database import engine
        from app.schemas.accounts import AccountCreate, TransactionReverseCreate
        from app.schemas.billing import InvoiceCreate
        from app.schemas.collections import ReceivablePaymentCreate
        from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate
        from app.services.accounts_service import AccountsService
        from app.services.billing_service import BillingService
        from app.services.collections_service import CollectionsService
        from app.services.purchases_service import PurchasesService
        with engine.connect() as connection:
            outer = connection.begin()
            db = Session(bind=connection, join_transaction_mode="create_savepoint")
            try:
                company, party = str(uuid4()), str(uuid4())
                db.execute(text("insert into companies(id,company_name) values(:id,'Aging regression')"), {"id": company})
                db.execute(text("insert into parties(id,company_id,party_type,legal_name) values(:id,:company,'customer_vendor','Aging Party')"), {"id": party, "company": company})
                accounts = AccountsService(db)
                account = accounts.create_account(company, AccountCreate(nickname="Aging bank", account_type="bank", is_company_account=True))
                billing, ar, ap = BillingService(db), CollectionsService(db), PurchasesService(db)
                invoice = billing.create_invoice(company, InvoiceCreate(customer_party_id=party, invoice_date=date(2026, 9, 10), subtotal=100, total=100,
                    amount_received=20, account_id=account["id"], payment_mode="bank"))
                receivable = ar.list_receivables(company)["items"][0]
                collection = ar.collect_receivable(str(receivable["id"]), company, ReceivablePaymentCreate(amount=80, account_id=account["id"], payment_mode="bank",
                    idempotency_key=str(uuid4()), payment_date=date(2026, 10, 5)))
                purchase = ap.create_purchase(company, PurchaseCreate(vendor_party_id=party, purchase_date=date(2026, 9, 10), subtotal=100, total=100,
                    amount_paid=20, account_id=account["id"], payment_mode="bank"))
                ap.add_purchase_payment(str(purchase["id"]), company, PurchasePaymentCreate(amount=80, account_id=account["id"], payment_mode="bank",
                    idempotency_key=str(uuid4()), payment_date=date(2026, 10, 5)))
                ap.create_purchase(company, PurchaseCreate(vendor_party_id=party, purchase_date=date(2026, 11, 1), subtotal=500, total=500))
                rows = lambda content: list(csv.DictReader(StringIO(content)))
                self.assertEqual(float(rows(ar.export_ar_aging_csv(company, "2026-09-30"))[0]["balance_amount"]), 80)
                self.assertEqual(float(rows(ap.export_ap_aging_csv(company, "2026-09-30"))[0]["balance_amount"]), 80)
                self.assertEqual(rows(ar.export_ar_aging_csv(company, "2026-10-10")), [])
                self.assertEqual(rows(ap.export_ap_aging_csv(company, "2026-10-10")), [])
                transactions = db.execute(text("select id from account_transactions where company_id=:company and amount=80 and reversal_of_transaction_id is null"), {"company": company}).scalars().all()
                for transaction in transactions:
                    accounts.reverse_transaction(str(transaction), company, TransactionReverseCreate(transaction_date=date(2026, 10, 20)))
                self.assertEqual(rows(ar.export_ar_aging_csv(company, "2026-10-10")), [])
                self.assertEqual(rows(ap.export_ap_aging_csv(company, "2026-10-10")), [])
                self.assertEqual(float(rows(ar.export_ar_aging_csv(company, "2026-10-31"))[0]["balance_amount"]), 80)
                self.assertEqual(float(rows(ap.export_ap_aging_csv(company, "2026-10-31"))[0]["balance_amount"]), 80)
            finally:
                db.close()
                outer.rollback()