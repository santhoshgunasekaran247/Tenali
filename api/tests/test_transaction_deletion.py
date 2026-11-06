import os
import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException

import test_multi_store


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only deletion tests")
class TransactionDeletionTests(unittest.TestCase):
    tearDown = test_multi_store.MultiStoreTests.tearDown
    stock = test_multi_store.MultiStoreTests.stock

    def setUp(self):
        test_multi_store.MultiStoreTests.setUp(self)
        from schema_support import apply_refund_settlement_migration
        from app.services.transaction_deletion import TransactionDeletionService
        apply_refund_settlement_migration(self.connection)
        self.service = TransactionDeletionService(self.db, self.company)

    def as_role(self, role):
        self.db.info["tenant_context"] = {"company_id": self.company, "role": role, "user_id": None, "display_name": "Tester"}

    def count(self, table, **where):
        clause = " and ".join(f"{key}=:{key}" for key in where) or "true"
        return self.db.execute(self.text(f"select count(*) from {table} where {clause}"), where).scalar_one()

    def remove(self, kind, record_id=None, cascade=False, **overrides):
        preview = self.service.preview(kind, record_id, cascade)
        args = {"token": preview["token"], "confirm_text": preview["confirm_text"], "reason": "Entered by mistake"}
        args.update(overrides)
        return preview, self.service.delete(kind, record_id, cascade=cascade, **args)

    def paid_purchase(self, quantity=3):
        from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate
        from app.services.purchases_service import PurchasesService
        purchases = PurchasesService(self.db)
        purchase = purchases.create_purchase(self.company, PurchaseCreate(
            vendor_party_id=self.party, purchase_date=date(2026, 11, 6), bill_number="V-1", received_now=True,
            lines=[{"product_id": self.product, "description": "x", "hsn": "8516", "quantity": quantity, "rate": 100}]))
        purchases.add_purchase_payment(str(purchase["id"]), self.company, PurchasePaymentCreate(
            amount=50, account_id=self.bank["id"], payment_mode="bank", idempotency_key=f"pay-{uuid4().hex}",
            payment_date=date(2026, 11, 7)))
        payment = self.db.execute(self.text("select id from purchase_payments where purchase_id=:id"), {"id": purchase["id"]}).scalar_one()
        return str(purchase["id"]), str(payment)

    def test_only_owner_or_admin(self):
        purchase_id, _ = self.paid_purchase()
        self.as_role("staff")
        with self.assertRaises(HTTPException) as denied:
            self.service.preview("purchase", purchase_id)
        self.assertEqual(denied.exception.status_code, 403)

    def test_purchase_needs_cascade_then_reverts_stock_payment_and_archives(self):
        purchase_id, payment_id = self.paid_purchase()
        self.assertEqual(self.stock(self.main), Decimal("13"))
        self.as_role("owner")
        preview = self.service.preview("purchase", purchase_id)
        self.assertFalse(preview["can_delete"])
        self.assertEqual(preview["critical"][0]["id"], payment_id)
        self.assertEqual({row["table"] for row in preview["critical"]}, {"purchase_payments", "account_transactions"})
        tables = {row["table"] for row in preview["deletes"]}
        self.assertTrue({"purchases", "purchase_payments", "account_transactions", "stock_movements"} <= tables, tables)
        self.assertEqual([(c["current"], c["change"], c["after"]) for c in preview["stock_changes"]], [(13.0, -3.0, 10.0)])
        self.assertEqual([c["change"] for c in preview["account_changes"]], [50.0])

        with self.assertRaises(HTTPException) as needs_cascade:
            self.service.delete("purchase", purchase_id, preview["token"], preview["confirm_text"], "Mistake")
        self.assertEqual(needs_cascade.exception.status_code, 409)
        with self.assertRaises(HTTPException) as stale:
            self.remove("purchase", purchase_id, cascade=True, token="0" * 64)
        self.assertEqual(stale.exception.status_code, 409)
        with self.assertRaises(HTTPException) as wrong_text:
            self.remove("purchase", purchase_id, cascade=True, confirm_text="delete")
        self.assertEqual(wrong_text.exception.status_code, 422)
        with self.assertRaises(HTTPException) as no_reason:
            self.remove("purchase", purchase_id, cascade=True, reason="  ")
        self.assertEqual(no_reason.exception.status_code, 422)

        preview, result = self.remove("purchase", purchase_id, cascade=True)
        self.assertEqual(self.stock(self.main), Decimal("10"))
        self.assertEqual(self.count("purchases", id=purchase_id), 0)
        self.assertEqual(self.count("purchase_payments", id=payment_id), 0)
        self.assertEqual(self.count("account_transactions", source_id=payment_id), 0)
        archived = dict(self.db.execute(self.text("""select entity_type, count(*) from deleted_records
            where deletion_id=:id group by entity_type"""), {"id": result["deletion_id"]}).all())
        self.assertEqual(archived["purchases"], 1)
        self.assertEqual(archived["purchase_payments"], 1)
        line_items = self.db.execute(self.text("""select payload->'line_items' from deleted_records
            where deletion_id=:id and entity_type='purchases'"""), {"id": result["deletion_id"]}).scalar_one()
        self.assertEqual(line_items[0]["product_id"], self.product)
        self.assertEqual(self.service.history()["items"][0]["reason"], "Entered by mistake")
        rows = [row for row in self.inventory.stock_reconciliation()["items"] if str(row["product_id"]) == self.product]
        self.assertTrue(all(Decimal(str(row["difference"])) == 0 for row in rows), rows)

    def test_payment_alone_reopens_bill(self):
        purchase_id, payment_id = self.paid_purchase()
        self.as_role("admin")
        preview, _ = self.remove("purchase_payment", payment_id)
        self.assertEqual(preview["critical"], [])
        bill = self.db.execute(self.text("select amount_paid, payment_status from purchases where id=:id"), {"id": purchase_id}).one()
        self.assertEqual((Decimal(bill[0]), bill[1]), (Decimal("0"), "UNPAID"))

    def test_sold_stock_and_invoices_block(self):
        from app.schemas.billing import InvoiceCreate
        from app.services.billing_service import BillingService
        purchase_id, _ = self.paid_purchase(quantity=2)
        self.db.execute(self.text("update stock_balances set quantity=1 where company_id=:company and store_id=:store"),
                        {"company": self.company, "store": self.main})
        self.as_role("owner")
        preview = self.service.preview("purchase", purchase_id, cascade=True)
        self.assertFalse(preview["can_delete"])
        self.assertIn("already been sold", preview["blockers"][0])
        with self.assertRaises(HTTPException) as blocked:
            self.remove("purchase", purchase_id, cascade=True)
        self.assertEqual(blocked.exception.status_code, 422)

        invoice = BillingService(self.db).create_invoice(self.company, InvoiceCreate(customer_party_id=self.party,
            place_of_supply="33 - Tamil Nadu", invoice_date=date(2026, 11, 8), subtotal=100))
        preview = self.service.preview("invoice", str(invoice["id"]))
        self.assertIn("Cancel the invoice", preview["blockers"][0])

    def test_database_rejects_deletes_outside_a_reviewed_batch(self):
        from sqlalchemy.exc import DBAPIError
        _, payment_id = self.paid_purchase()
        with self.assertRaises(DBAPIError) as rejected:
            with self.db.begin_nested():
                self.db.execute(self.text("delete from account_transactions where source_id=:id"), {"id": payment_id})
        self.assertIn("reviewed deletion", str(rejected.exception))

    def test_transfer_with_reversal_and_manual_transaction(self):
        from app.schemas.accounts import AccountTransactionCreate, TransactionReverseCreate
        from app.schemas.inventory import StockTransferCreate
        transfer = self.inventory.transfer_stock(StockTransferCreate(from_store_id=self.main, to_store_id=self.shop["id"],
                                                                     notes="Stock shop", lines=[{"product_id": self.product, "quantity": 4}]))
        self.inventory.reverse_transfer(str(transfer["id"]), "Mistake")
        tx = self.accounts.create_transaction(self.company, AccountTransactionCreate(to_account_id=self.bank["id"], amount=200,
                                                                                    reference="Cash in", transaction_date=date(2026, 11, 6)))
        self.accounts.reverse_transaction(str(tx["id"]), self.company, TransactionReverseCreate(notes="Wrong"))
        self.as_role("owner")

        preview = self.service.preview("stock_transfer", str(transfer["id"]))
        self.assertEqual(len(preview["critical"]), 1)
        self.assertEqual(preview["stock_changes"], [])
        self.remove("stock_transfer", str(transfer["id"]), cascade=True)
        self.assertEqual((self.stock(self.main), self.stock(self.shop["id"])), (Decimal("10"), Decimal("0")))
        self.assertEqual(self.count("stock_movements", reference_id=str(transfer["id"])), 0)

        preview, _ = self.remove("account_transaction", str(tx["id"]))
        self.assertEqual(preview["deletes"][0]["count"], 2)
        self.assertEqual(self.count("account_transactions", company_id=self.company), 0)

    def test_customer_receipts_reopen_invoice(self):
        from app.schemas.billing import InvoiceCreate
        from app.schemas.collections import ReceivablePaymentCreate
        from app.services.billing_service import BillingService
        from app.services.collections_service import CollectionsService
        invoice = BillingService(self.db).create_invoice(self.company, InvoiceCreate(
            customer_party_id=self.party, place_of_supply="33 - Tamil Nadu", subtotal=150, amount_received=50,
            account_id=self.bank["id"], payment_mode="bank", invoice_date=date(2026, 11, 6)))
        receivable = self.db.execute(self.text("select id from receivables where invoice_id=:id"), {"id": invoice["id"]}).scalar_one()
        CollectionsService(self.db).collect_receivable(str(receivable), self.company, ReceivablePaymentCreate(
            amount=75, account_id=self.bank["id"], payment_mode="bank", payment_date=date(2026, 11, 7), idempotency_key=str(uuid4())))
        payment = self.db.execute(self.text("select id from receivable_payments where receivable_id=:id"), {"id": receivable}).scalar_one()
        direct = self.db.execute(self.text("select id from account_transactions where source_type='invoice' and source_id=:id"),
                                 {"id": invoice["id"]}).scalar_one()
        received = lambda: [Decimal(value) for value in self.db.execute(self.text("""select r.amount_received, i.amount_received
            from receivables r join invoices i on i.id=r.invoice_id where r.id=:id"""), {"id": receivable}).one()]
        self.assertEqual(received(), [Decimal("125"), Decimal("125")])
        self.as_role("owner")
        self.remove("receivable_payment", str(payment))
        self.assertEqual(received(), [Decimal("50"), Decimal("50")])
        preview, _ = self.remove("account_transaction", str(direct))
        self.assertTrue(any("unpaid again" in warning for warning in preview["warnings"]))
        self.assertEqual(received(), [Decimal("0"), Decimal("0")])

    def test_reset_erases_transactions_keeps_masters(self):
        self.paid_purchase()
        self.as_role("owner")
        preview = self.service.preview("all")
        self.assertEqual(preview["confirm_text"], "DELETE ALL TRANSACTIONS")
        self.assertIn("stock_movements", {row["table"] for row in preview["deletes"]})
        self.remove("all")
        for table in ("purchases", "purchase_payments", "account_transactions", "stock_movements", "stock_balances"):
            self.assertEqual(self.count(table, company_id=self.company), 0, table)
        self.assertEqual(self.count("products", id=self.product), 1)
        self.assertEqual(self.count("accounts", company_id=self.company), 3)
        with self.assertRaises(HTTPException) as empty:
            self.remove("all")
        self.assertEqual(empty.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
