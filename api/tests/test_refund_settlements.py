import os
import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException

import test_multi_store


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only refund tests")
class RefundSettlementTests(unittest.TestCase):
    tearDown = test_multi_store.MultiStoreTests.tearDown
    stock = test_multi_store.MultiStoreTests.stock

    def setUp(self):
        test_multi_store.MultiStoreTests.setUp(self)
        from schema_support import apply_refund_settlement_migration
        apply_refund_settlement_migration(self.connection)
        self.as_role("owner")

    def as_role(self, role, modules=None):
        self.db.info["tenant_context"] = {"company_id": self.company, "role": role, "user_id": None,
                                          "display_name": "Tester", "modules": modules}

    def rows(self, sql, **params):
        return [dict(row) for row in self.db.execute(self.text(sql), {"company": self.company, **params}).mappings().all()]

    def paid_invoice(self):
        from app.schemas.billing import InvoiceCreate
        from app.schemas.collections import ReceivablePaymentCreate
        from app.services.billing_service import BillingService
        from app.services.collections_service import CollectionsService
        invoice = BillingService(self.db).create_invoice(self.company, InvoiceCreate(
            customer_party_id=self.party, place_of_supply="33 - Tamil Nadu", invoice_date=date.today(),
            amount_received=400, account_id=self.bank["id"], payment_mode="bank",
            lines=[{"product_id": self.product, "description": "Kettle", "hsn": "8516", "quantity": 2, "rate": 500}]))
        receivable = self.db.execute(self.text("select id from receivables where invoice_id=:id"), {"id": invoice["id"]}).scalar_one()
        CollectionsService(self.db).collect_receivable(str(receivable), self.company, ReceivablePaymentCreate(
            amount=300, account_id=self.bank["id"], payment_mode="bank", payment_date=date.today(), idempotency_key=str(uuid4())))
        return str(invoice["id"]), str(receivable)

    def test_cancel_paid_invoice_reverses_receipts_and_opens_refunds(self):
        from app.services.document_cancellation import Cancellation, cancel_document
        invoice_id, receivable = self.paid_invoice()
        self.assertEqual(self.stock(self.main), Decimal("8"))
        with self.assertRaises(HTTPException) as refused:
            cancel_document(self.db, self.company, "invoice", invoice_id, Cancellation(reason="Wrong customer"))
        self.assertEqual(refused.exception.status_code, 422)

        result = cancel_document(self.db, self.company, "invoice", invoice_id,
                                 Cancellation(reason="Wrong customer", reverse_payments=True))
        self.assertEqual(sorted(Decimal(item["amount"]) for item in result["refunds"]), [Decimal("300"), Decimal("400")])
        invoice = self.rows("select status, amount_received, cancellation_reason from invoices where id=:id", id=invoice_id)[0]
        self.assertEqual((invoice["status"], invoice["amount_received"], invoice["cancellation_reason"]),
                         ("CANCELLED", Decimal("0"), "Wrong customer"))
        self.assertEqual(self.stock(self.main), Decimal("10"))
        # Nothing is deleted: both receipts stay, each with a reversal, and the collection is marked reversed.
        originals = self.rows("""select t.id from account_transactions t where t.company_id=:company and t.reversal_of_transaction_id is null
            and (t.source_type in ('invoice', 'receivable_payment'))""")
        self.assertEqual(len(originals), 2)
        reversals = self.rows("select from_account_id, to_account_id, amount from account_transactions where company_id=:company and reversal_of_transaction_id is not null")
        self.assertEqual({(str(row["from_account_id"]), row["to_account_id"]) for row in reversals}, {(str(self.bank["id"]), None)})
        self.assertEqual(self.rows("select count(*) as n from receivable_payments where receivable_id=:id and reversed_at is not null", id=receivable)[0]["n"], 1)

        from app.services.refund_settlements import RefundSettle, RefundSettlementsService
        service = RefundSettlementsService(self.db)
        listing = service.list("PENDING")
        self.assertEqual(len(listing["items"]), 2)
        self.assertEqual({item["direction"] for item in listing["items"]}, {"PAY_CUSTOMER"})
        self.assertEqual((listing["summary"]["customer_count"], Decimal(str(listing["summary"]["customer_amount"]))), (2, Decimal("700")))
        self.assertEqual(listing["items"][0]["original_account_name"], "Bank")

        from app.schemas.accounts import AccountCreate
        cash = self.accounts.create_account(self.company, AccountCreate(nickname="Cash drawer", account_type="cash"))
        target = next(item for item in listing["items"] if Decimal(str(item["amount"])) == Decimal("400"))
        settled = service.settle(target["id"], RefundSettle(account_id=str(cash["id"]), payment_mode="cash", reference="RF-1",
                                                            settled_on=date.today()))
        self.assertEqual(settled["status"], "SETTLED")
        reversal = self.rows("""select r.from_account_id, r.payment_mode, r.reference, r.description from account_transactions r
            join refund_settlements s on s.reversal_transaction_id=r.id where s.id=cast(:id as uuid)""", id=target["id"])[0]
        self.assertEqual((str(reversal["from_account_id"]), reversal["payment_mode"], reversal["reference"]), (str(cash["id"]), "cash", "RF-1"))
        self.assertTrue(reversal["description"].startswith("Refund settled"))
        with self.assertRaises(HTTPException) as again:
            service.settle(target["id"], RefundSettle(account_id=str(cash["id"])))
        self.assertEqual(again.exception.status_code, 409)
        with self.assertRaises(HTTPException) as future:
            other = next(item for item in listing["items"] if item["id"] != target["id"])
            service.settle(other["id"], RefundSettle(account_id=str(cash["id"]), settled_on=date(2999, 1, 1)))
        self.assertEqual(future.exception.status_code, 422)
        self.assertEqual(service.summary()["customer_count"], 1)

        from app.services.dashboard_service import DashboardService
        dashboard = DashboardService(self.db).summary()
        self.assertEqual(dashboard["refunds_pending"]["customer_count"], 1)
        self.assertIn("outstanding", dashboard["receivables"])

        # A full erase also removes refund settlements, before the transactions they reference.
        from app.services.transaction_deletion import TransactionDeletionService
        deletions = TransactionDeletionService(self.db, self.company)
        preview = deletions.preview("all")
        self.assertIn("refund_settlements", {row["table"] for row in preview["deletes"]})
        deletions.delete("all", None, token=preview["token"], confirm_text=preview["confirm_text"], reason="Fresh start")
        self.assertEqual(self.rows("select count(*) as n from refund_settlements where company_id=:company")[0]["n"], 0)

    def test_cancel_paid_purchase_expects_vendor_refund(self):
        from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate
        from app.services.document_cancellation import Cancellation, cancel_document
        from app.services.purchases_service import PurchasesService
        from app.services.refund_settlements import RefundSettle, RefundSettlementsService
        purchases = PurchasesService(self.db)
        purchase = purchases.create_purchase(self.company, PurchaseCreate(
            vendor_party_id=self.party, purchase_date=date.today(), bill_number="V-9", received_now=True,
            lines=[{"product_id": self.product, "description": "x", "hsn": "8516", "quantity": 3, "rate": 100}]))
        purchases.add_purchase_payment(str(purchase["id"]), self.company, PurchasePaymentCreate(
            amount=120, account_id=self.bank["id"], payment_mode="bank", idempotency_key=f"pay-{uuid4().hex}",
            payment_date=date.today()))
        self.assertEqual(self.stock(self.main), Decimal("13"))

        self.as_role("staff", modules=["purchases"])
        with self.assertRaises(HTTPException) as denied:
            cancel_document(self.db, self.company, "purchase", str(purchase["id"]),
                            Cancellation(reason="Returned", reverse_payments=True), commit=False)
        self.assertEqual(denied.exception.status_code, 403)
        self.db.rollback()

        self.as_role("staff", modules=["purchases", "accounts"])
        cancel_document(self.db, self.company, "purchase", str(purchase["id"]), Cancellation(reason="Returned", reverse_payments=True))
        purchase_row = self.rows("select status, amount_paid from purchases where id=:id", id=str(purchase["id"]))[0]
        self.assertEqual((purchase_row["status"], purchase_row["amount_paid"]), ("CANCELLED", Decimal("0")))
        self.assertEqual(self.stock(self.main), Decimal("10"))
        service = RefundSettlementsService(self.db)
        [refund] = service.list("PENDING")["items"]
        self.assertEqual((refund["direction"], refund["document_number"], Decimal(str(refund["amount"]))), ("RECEIVE_VENDOR", "V-9", Decimal("120")))
        service.settle(refund["id"], RefundSettle(account_id=str(self.bank["id"]), payment_mode="upi"))
        reversal = self.rows("""select r.from_account_id, r.to_account_id, r.payment_mode from account_transactions r
            join refund_settlements s on s.reversal_transaction_id=r.id where s.id=cast(:id as uuid)""", id=refund["id"])[0]
        self.assertEqual((reversal["from_account_id"], str(reversal["to_account_id"]), reversal["payment_mode"]), (None, str(self.bank["id"]), "upi"))
        self.assertEqual(service.summary()["vendor_count"], 0)


if __name__ == "__main__":
    unittest.main()
