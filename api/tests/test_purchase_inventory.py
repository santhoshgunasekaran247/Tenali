import os
import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException

import test_multi_store


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only purchase inventory tests")
class PurchaseInventoryTests(unittest.TestCase):
    tearDown = test_multi_store.MultiStoreTests.tearDown

    def setUp(self):
        test_multi_store.MultiStoreTests.setUp(self)
        from schema_support import apply_product_draft_migration
        apply_product_draft_migration(self.connection)
        from app.schemas.masters import HsnMasterCreate
        from app.services.masters_service import MastersService
        MastersService(self.db).create_hsn(HsnMasterCreate(code="7408", description="Copper wire", gst_rate=18), self.company)

    def product_row(self, product_id):
        return self.db.execute(self.text("select * from products where id=:id"), {"id": product_id}).mappings().one()

    def stock_of(self, product_id):
        return self.db.execute(self.text("select coalesce(sum(quantity),0) from stock_balances where product_id=:product"),
                               {"product": product_id}).scalar_one()

    def purchase(self, lines, **extra):
        from app.schemas.purchases import PurchaseCreate
        from app.services.purchases_service import PurchasesService
        return PurchasesService(self.db).create_purchase(self.company, PurchaseCreate(
            vendor_party_id=self.party, purchase_date=date(2026, 11, 6), lines=lines, **extra))

    def sell(self, product_id, hsn="8516"):
        from app.schemas.billing import InvoiceCreate
        from app.services.billing_service import BillingService
        return BillingService(self.db).create_invoice(self.company, InvoiceCreate(
            customer_party_id=self.party, place_of_supply="33 - Tamil Nadu", invoice_date=date(2026, 11, 6),
            lines=[{"product_id": product_id, "description": "x", "hsn": hsn, "quantity": 1, "rate": 500}]))

    def test_product_without_hsn_takes_line_hsn_and_keeps_it(self):
        self.db.execute(self.text("update products set hsn_code=null where id=:id"), {"id": self.product})
        with self.assertRaises(HTTPException) as error:
            self.sell(self.product, hsn="9999")
        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("Choose an HSN/SAC code", error.exception.detail)
        invoice = self.sell(self.product, hsn="7408")
        self.assertEqual(invoice["document_data"]["lines"][0]["hsn"], "7408")
        self.assertEqual(self.product_row(self.product)["hsn_code"], "7408")
        # Once set, the product's own code wins over whatever the line sends.
        again = self.sell(self.product, hsn="8516")
        self.assertEqual(again["document_data"]["lines"][0]["hsn"], "7408")

    def test_new_purchase_line_creates_draft_product_and_received_now_books_stock(self):
        line = {"new_product": True, "description": "  Copper   wire ", "hsn": "7408", "quantity": 4, "rate": 250}
        pending = self.purchase([dict(line)])
        product_id = pending["line_items"][0]["product_id"]
        product = self.product_row(product_id)
        self.assertEqual((product["name"], product["hsn_code"], product["is_draft"], product["catalog_visible"]), ("Copper wire", "7408", True, False))
        self.assertEqual(str(product["preferred_vendor_id"]), self.party)
        offer = self.db.execute(self.text("select buying_price from vendor_contributions where product_id=:id and vendor_id=:vendor"),
                                {"id": product_id, "vendor": self.party}).scalar_one()
        self.assertEqual(Decimal(offer), Decimal("250"))
        self.assertNotIn("new_product", pending["line_items"][0])
        self.assertEqual(pending["receipt_status"], "PENDING")
        self.assertEqual(self.stock_of(product_id), 0)

        with self.assertRaises(HTTPException) as duplicate:
            self.purchase([dict(line)])
        self.assertEqual(duplicate.exception.status_code, 409)

        received = self.purchase([{"product_id": product_id, "description": "x", "hsn": "7408", "quantity": 3, "rate": 250}], received_now=True)
        self.assertEqual(received["receipt_status"], "RECEIVED")
        self.assertIsNotNone(received["received_at"])
        self.assertEqual(self.stock_of(product_id), 3)

        with self.assertRaises(HTTPException) as draft_sale:
            self.sell(product_id, hsn="7408")
        self.assertIn("draft product", draft_sale.exception.detail)
        confirmed = self.inventory.confirm_draft(product_id)
        self.assertFalse(confirmed["is_draft"])
        self.sell(product_id, hsn="7408")
        self.assertEqual(self.stock_of(product_id), 2)

    def test_merge_draft_moves_stock_history_bills_and_vendor_offer(self):
        from app.schemas.inventory import ProductInput, ProductMerge
        from app.schemas.purchases import PurchaseReceiptConfirm
        from app.services.purchases_service import PurchasesService
        target = str(self.inventory.save_product(ProductInput(name="Copper rod", catalog_visible=False))["id"])
        received = self.purchase([{"new_product": True, "description": "Copper rods", "hsn": "7408", "quantity": 4, "rate": 250}], received_now=True)
        draft = received["line_items"][0]["product_id"]
        pending = self.purchase([{"product_id": draft, "description": "x", "hsn": "7408", "quantity": 3, "rate": 260}])

        self.db.info["tenant_context"] = {"role": "staff", "company_id": self.company}
        with self.assertRaises(HTTPException) as denied:
            self.inventory.merge_draft(draft, ProductMerge(target_product_id=target))
        self.assertEqual(denied.exception.status_code, 403)
        self.db.info["tenant_context"] = {"role": "owner", "company_id": self.company}
        with self.assertRaises(HTTPException) as not_draft:
            self.inventory.merge_draft(target, ProductMerge(target_product_id=self.product))
        self.assertEqual(not_draft.exception.status_code, 422)

        merged = self.inventory.merge_draft(draft, ProductMerge(target_product_id=target))
        self.db.info.pop("tenant_context", None)
        self.assertEqual(Decimal(merged["stock_qty"]), Decimal("4"))
        self.assertEqual(merged["hsn_code"], "7408")
        self.assertEqual(str(merged["preferred_vendor_id"]), self.party)
        self.assertEqual([str(offer["vendor_id"]) for offer in merged["offers"]], [self.party])
        self.assertIsNone(self.db.execute(self.text("select id from products where id=:id"), {"id": draft}).scalar_one_or_none())
        self.assertEqual(self.db.execute(self.text("select count(*) from stock_movements where product_id=:id"), {"id": target}).scalar_one(), 1)
        bill = self.db.execute(self.text("select line_items from purchases where id=:id"), {"id": pending["id"]}).scalar_one()
        self.assertEqual(bill[0]["product_id"], target)

        PurchasesService(self.db).confirm_purchase_receipt(str(pending["id"]), self.company, PurchaseReceiptConfirm())
        self.assertEqual(self.stock_of(target), 7)
        check = [row for row in self.inventory.stock_reconciliation()["items"] if str(row["product_id"]) == target]
        self.assertTrue(check and all(Decimal(str(row["difference"])) == 0 for row in check), check)

    def test_received_now_skips_service_bills_and_default_waits_for_receipt(self):
        before = self.stock_of(self.product)
        line = {"product_id": self.product, "description": "x", "hsn": "8516", "quantity": 2, "rate": 800}
        service = self.purchase([dict(line)], received_now=True, receipt_type="SERVICE")
        self.assertEqual(service["receipt_status"], "PENDING")
        self.assertEqual(self.stock_of(self.product), before)
        received = self.purchase([dict(line)], received_now=True)
        self.assertEqual(received["receipt_status"], "RECEIVED")
        self.assertEqual(self.stock_of(self.product), before + 2)


if __name__ == "__main__":
    unittest.main()
