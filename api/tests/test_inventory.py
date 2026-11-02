import unittest
import os
from decimal import Decimal
from datetime import date, timedelta
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.inventory import ProductInput, VariantInput, VendorOfferInput
from app.services.inventory_pricing import resolve_catalog_price
from app.services.catalog_service import _public_product
from app.services.inventory_service import InventoryService


class InventoryRulesTests(unittest.TestCase):
    def test_discount_and_price_calculate_both_ways(self):
        self.assertEqual(resolve_catalog_price(1000, None, 15, "discount")["catalog_price"], Decimal("850.00"))
        self.assertEqual(resolve_catalog_price(1000, 850, 0, "price")["effective_discount"], Decimal("15.00"))

    def test_vendor_mrp_changes_follow_selected_pricing_mode(self):
        self.assertEqual(resolve_catalog_price(2000, 850, 15, "price")["catalog_price"], Decimal("850"))
        self.assertEqual(resolve_catalog_price(2000, 850, 15, "discount")["catalog_price"], Decimal("1700.00"))

    def test_missing_vendor_mrp_does_not_invent_a_discount_price(self):
        self.assertIsNone(resolve_catalog_price(None, None, 15, "discount")["catalog_price"])
        with self.assertRaises(HTTPException):
            resolve_catalog_price(100, 110, 0, "price")

    def test_product_and_reorder_validation(self):
        self.assertEqual(ProductInput(name="Test").minimum_order_quantity, 1)
        self.assertEqual(ProductInput(name="Test", minimum_order_quantity=100).minimum_order_quantity, 100)
        for minimum in [0, -1, 101, 1.5, True, "5"]:
            with self.assertRaises(ValidationError):
                ProductInput(name="Test", minimum_order_quantity=minimum)
        with self.assertRaises(ValidationError):
            ProductInput(name="Test", discount_percent=101)
        with self.assertRaises(ValidationError):
            ProductInput(name="Test", reorder_enabled=True, reorder_level=10, reorder_target=5)
        with self.assertRaises(ValidationError):
            VendorOfferInput(vendor_id="00000000-0000-0000-0000-000000000001", available_quantity=-1)

    def test_zero_and_invalid_prices(self):
        self.assertEqual(resolve_catalog_price(0, None, 10, "discount")["catalog_price"], Decimal("0.00"))
        self.assertIsNone(resolve_catalog_price(None, 100, 0, "price")["effective_discount"])
        for mrp, price, discount, mode in [(0, 1, 0, "price"), (100, -1, 0, "price"),
                                             (100, None, 101, "discount"), (100, 10, 0, "bad")]:
            with self.assertRaises(HTTPException):
                resolve_catalog_price(mrp, price, discount, mode)

    def test_variant_inherits_product_pricing_against_variant_mrp(self):
        self.assertEqual(VariantInput(variant_name="Large Red").pricing_mode, "inherit")
        service = object.__new__(InventoryService)
        parent = {"pricing_mode": "discount", "selling_price": None, "discount_percent": Decimal("15")}
        variant = {"pricing_mode": "inherit", "preferred_vendor_id": "vendor", "selling_price": None}
        offers = [{"vendor_id": "vendor", "mrp": Decimal("2000"), "buying_price": Decimal("800"),
                   "vendor_name": "Supplier", "is_active": True, "vendor_active": True}]
        result = service._enrich(variant, offers, Decimal("2"), parent=parent)
        self.assertEqual(result["catalog_price"], Decimal("1700.00"))
        self.assertEqual(result["stock_qty"], Decimal("2"))

    def test_public_projection_uses_effective_prices_and_hides_internal_keys(self):
        row = dict(id="product", reference_mrp=Decimal("1000"), selling_price=None,
                   pricing_mode="discount", discount_percent=Decimal("15"), preferred_vendor_id="vendor")
        result = _public_product(row)
        self.assertEqual(result["mrp_display"], "1000")
        self.assertEqual(result["selling_price_display"], "850.00")
        for key in ["reference_mrp", "selling_price", "pricing_mode", "preferred_vendor_id", "buying_price", "phone"]:
            self.assertNotIn(key, result)


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only inventory database tests")
class InventoryDatabaseTests(unittest.TestCase):
    def setUp(self):
        from dotenv import load_dotenv
        load_dotenv("api/.env")
        from sqlalchemy import text
        from sqlalchemy.orm import Session
        from app.core.database import engine
        self.text = text
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        from schema_support import apply_customer_migration, apply_product_minimum_migration, apply_inventory_deletion_migration
        apply_customer_migration(self.connection)
        apply_product_minimum_migration(self.connection)
        apply_inventory_deletion_migration(self.connection)
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        self.company, self.other, self.vendor_a, self.vendor_b = [str(uuid4()) for _ in range(4)]
        for company in [self.company, self.other]:
            self.db.execute(text("insert into companies(id,company_name) values(:id,'Inventory regression fixture')"), {"id": company})
            from schema_support import ensure_default_store
            ensure_default_store(self.db, company)
        for vendor in [self.vendor_a, self.vendor_b]:
            self.db.execute(text("""insert into parties(id,company_id,party_type,legal_name,phone,email)
                values(:id,:company,'vendor','PRIVATE SUPPLIER','PRIVATE PHONE','private@example.com')"""), {"id": vendor, "company": self.company})
        self.service = InventoryService(self.db, self.company)
        self.payload = ProductInput(name="Shared regression product", pricing_mode="discount", discount_percent=10,
                                    catalog_visible=True, reorder_enabled=True, reorder_level=3, reorder_target=10)
        self.product = self.service.save_product(self.payload)
        self.product_id = str(self.product["id"])

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def test_multiple_vendors_do_not_duplicate_products(self):
        from app.schemas.inventory import BulkVendorMapping
        self.service.save_offer(self.product_id, VendorOfferInput(vendor_id=self.vendor_a, mrp=1000, buying_price=600, available_quantity=80))
        product = self.service.save_offer(self.product_id, VendorOfferInput(vendor_id=self.vendor_b, mrp=2000, buying_price=900))
        self.assertEqual(len(self.service.list_products()["items"]), 1)
        self.assertEqual(product["catalog_price"], Decimal("900.00"))
        self.assertEqual(product["stock_qty"], 0)
        self.assertEqual(product["vendor_available_quantity"], Decimal("80"))
        updated = self.payload.model_copy(update={"preferred_vendor_id": self.product["id"].__class__(self.vendor_b)})
        product = self.service.save_product(updated, self.product_id)
        self.assertEqual(product["catalog_price"], Decimal("1800.00"))
        self.service.bulk_map(BulkVendorMapping(vendor_id=self.vendor_a, product_ids=[self.product_id]))
        self.assertEqual(len(self.service.detail(self.product_id)["offers"]), 2)

    def test_variants_stock_and_persistent_reminders(self):
        from app.schemas.inventory import StockAdjustment, ReorderReminder
        self.service.save_offer(self.product_id, VendorOfferInput(vendor_id=self.vendor_a, mrp=1000))
        product = self.service.save_variant(self.product_id, VariantInput(variant_name="Large Blue", size="Large", colour="Blue"))
        variant_id = str(product["variants"][0]["id"])
        product = self.service.save_offer(self.product_id, VendorOfferInput(vendor_id=self.vendor_a, variant_id=variant_id, mrp=2000))
        self.assertEqual(product["variants"][0]["catalog_price"], Decimal("1800.00"))
        self.service.adjust_stock(self.product_id, StockAdjustment(variant_id=variant_id, direction="IN", quantity=2, notes="Test receipt"))
        self.assertEqual(len(self.service.alerts()["items"]), 1)
        with self.assertRaises(HTTPException):
            self.service.adjust_stock(self.product_id, StockAdjustment(variant_id=variant_id, direction="OUT", quantity=3, notes="Invalid outbound"))
        self.service.adjust_stock(self.product_id, StockAdjustment(variant_id=variant_id, direction="IN", quantity=10, notes="Restocked"))
        self.assertEqual(self.service.alerts()["items"], [])
        self.assertEqual(len(self.service.movements(self.product_id)["items"]), 2)
        self.assertEqual(len(self.service.remind(self.product_id, ReorderReminder(reminder_date=date.today()))["items"]), 1)
        self.assertEqual(self.service.remind(self.product_id, ReorderReminder(reminder_date=date.today()+timedelta(days=2)))["items"], [])

    def test_shared_customer_catalog_visibility_and_privacy(self):
        from app.schemas.catalog import CatalogProductResponse
        from app.services.catalog_service import CatalogService
        self.service.save_offer(self.product_id, VendorOfferInput(vendor_id=self.vendor_a, mrp=1000, buying_price=321))
        catalog = CatalogService(self.db)
        detail = CatalogProductResponse.model_validate(catalog.product_detail(self.product_id, self.company))
        self.assertEqual(detail.product.selling_price_display, "900.00")
        for field in ["buying_price", "vendor_id", "PRIVATE SUPPLIER", "PRIVATE PHONE", "private@example.com"]:
            self.assertNotIn(field, detail.model_dump_json())
        hidden = self.payload.model_copy(update={"catalog_visible": False})
        self.service.save_product(hidden, self.product_id)
        self.assertEqual(catalog.list(company_id=self.company)["products"], [])
        with self.assertRaises(HTTPException):
            catalog.product_detail(self.product_id, self.company)

    def test_company_and_variant_boundaries(self):
        from app.schemas.inventory import BulkVendorMapping
        with self.assertRaises(HTTPException):
            InventoryService(self.db, self.other).detail(self.product_id)
        with self.assertRaises(HTTPException):
            self.service.save_offer(self.product_id, VendorOfferInput(vendor_id=self.vendor_a, variant_id=str(uuid4()), mrp=1000))
        with self.assertRaises(HTTPException):
            self.service.bulk_map(BulkVendorMapping(vendor_id=self.vendor_a, product_ids=[self.product_id, str(uuid4())]))
        self.assertEqual(self.service.detail(self.product_id)["offers"], [])

    def test_delete_unused_product_removes_variants_offers_and_zero_balances(self):
        self.service.save_variant(self.product_id, VariantInput(variant_name="Unused blue"))
        self.service.save_offer(self.product_id, VendorOfferInput(vendor_id=self.vendor_a))
        store = self.db.execute(self.text("select id from stores where company_id=:company and is_default"),
                                {"company": self.company}).scalar_one()
        self.db.execute(self.text("""insert into stock_balances(company_id,store_id,product_id,quantity)
            values(:company,:store,:product,0)"""), {"company": self.company, "store": store, "product": self.product_id})
        self.db.info["tenant_context"] = {"company_id": self.company, "role": "owner"}
        self.db.commit()
        self.assertEqual(self.service.delete_product(self.product_id), {"deleted": True, "id": self.product_id})
        for table in ["products", "product_variants", "vendor_contributions", "stock_balances"]:
            key = "id" if table == "products" else "product_id"
            self.assertEqual(self.db.execute(self.text(f"select count(*) from {table} where {key}=:id"),
                                             {"id": self.product_id}).scalar_one(), 0)
        with self.assertRaises(HTTPException) as missing:
            self.service.delete_product(self.product_id)
        self.assertEqual(missing.exception.status_code, 404)

    def test_delete_requires_owner_or_admin_and_rejects_other_company(self):
        other_product = self.db.execute(self.text("""insert into products(company_id,portal_product_id,name)
            values(:company,'DELETE-OTHER','Other company product') returning id"""),
            {"company": self.other}).scalar_one()
        for role in ["viewer", "staff", None]:
            self.db.info["tenant_context"] = {"company_id": self.company, "role": role}
            with self.assertRaises(HTTPException) as denied:
                self.service.delete_product(self.product_id)
            self.assertEqual(denied.exception.status_code, 403)
        self.db.info["tenant_context"] = {"company_id": self.company, "role": "admin"}
        self.db.commit()
        self.assertEqual(self.db.execute(self.text("delete from products where id=:id"), {"id": other_product}).rowcount, 0)
        other_service = object.__new__(InventoryService)
        other_service.db, other_service.company_id = self.db, self.other
        with self.assertRaises(HTTPException) as missing:
            other_service.delete_product(self.product_id)
        self.assertEqual(missing.exception.status_code, 404)
        self.assertTrue(self.service.delete_product(self.product_id)["deleted"])

    def test_delete_blocks_balance_and_zero_net_movement_history(self):
        from app.schemas.inventory import StockAdjustment
        self.service.adjust_stock(self.product_id, StockAdjustment(direction="IN", quantity=2, notes="Deletion test"))
        self.db.info["tenant_context"] = {"company_id": self.company, "role": "owner"}
        with self.assertRaises(HTTPException) as used:
            self.service.delete_product(self.product_id)
        self.assertEqual(used.exception.status_code, 409)
        self.service.adjust_stock(self.product_id, StockAdjustment(direction="OUT", quantity=2, notes="Deletion test zero"))
        with self.assertRaises(HTTPException) as history:
            self.service.delete_product(self.product_id)
        self.assertEqual(history.exception.status_code, 409)

    def test_delete_blocks_json_invoice_and_purchase_history(self):
        import json
        self.db.info["tenant_context"] = {"company_id": self.company, "role": "owner"}
        params = {"company": self.company, "party": self.vendor_a, "product": self.product_id,
                  "data": json.dumps({"lines": [{"product_id": self.product_id}]})}
        invoice = self.db.execute(self.text("""insert into invoices(company_id,customer_party_id,invoice_number,
            invoice_date,subtotal,gst_total,total,document_data) values(:company,:party,'DELETE-TEST',current_date,0,0,0,cast(:data as jsonb)) returning id"""), params).scalar_one()
        with self.assertRaises(HTTPException) as used:
            self.service.delete_product(self.product_id)
        self.assertEqual(used.exception.status_code, 409)
        self.db.execute(self.text("delete from invoices where id=:id"), {"id": invoice})
        params["data"] = json.dumps([{"product_id": self.product_id}])
        self.db.execute(self.text("""insert into purchases(company_id,vendor_party_id,purchase_date,subtotal,gst_total,total,line_items)
            values(:company,:party,current_date,0,0,0,cast(:data as jsonb))"""), params)
        with self.assertRaises(HTTPException) as used:
            self.service.delete_product(self.product_id)
        self.assertEqual(used.exception.status_code, 409)

    def test_missing_sources_respect_store_scope(self):
        from app.schemas.inventory import ExternalMovementSource, StockAdjustment
        second = self.db.execute(self.text("""insert into stores(company_id,code,name,kind,holds_stock,state_code)
            values(:company,'SECOND','Other stock room','warehouse',true,'33') returning id"""),
            {"company": self.company}).scalar_one()
        self.service.adjust_stock(self.product_id, StockAdjustment(direction="IN", quantity=1, notes="Missing fixture"),
                                  reference_type="invoice", reference_id=str(uuid4()))
        self.service.adjust_stock(self.product_id, StockAdjustment(direction="IN", quantity=1, notes="Missing fixture"),
                                  reference_type="invoice", reference_id=str(uuid4()), store_id=str(second))
        rows = self.service.missing_movement_sources()["items"]
        self.assertEqual(len(rows), 2)
        self.db.info["tenant_context"] = {"company_id": self.company, "role": "staff", "store_ids": [str(second)]}
        scoped = self.service.missing_movement_sources()["items"]
        self.assertEqual(len(scoped), 1)
        self.assertEqual(str(scoped[0]["store_id"]), str(second))
        self.assertEqual(scoped[0]["store_code"], "SECOND")
        denied_id = next(str(row["id"]) for row in rows if str(row["store_id"]) != str(second))
        with self.assertRaises(HTTPException):
            self.service.attribute_external_source(denied_id, ExternalMovementSource(external_reference="Paper", notes="Filed"))
        self.db.info["tenant_context"]["store_ids"] = []
        self.assertEqual(self.service.missing_movement_sources()["items"], [])

    def test_delete_blocks_order_and_transfer_json_without_movements(self):
        import json
        self.db.info["tenant_context"] = {"company_id": self.company, "role": "owner"}
        shopper = self.db.execute(self.text("""insert into shopper_accounts(company_id,email,display_name,supabase_uid)
            values(:company,'delete-fixture@example.test','Deletion fixture',:uid) returning id"""),
            {"company": self.company, "uid": str(uuid4())}).scalar_one()
        params = {"company": self.company, "shopper": shopper, "key": uuid4(), "hash": "deletion-fixture",
                  "items": json.dumps([{"product_id": self.product_id}])}
        order = self.db.execute(self.text("""insert into shop_orders(company_id,shopper_id,request_key,request_hash,
            status,items,address,subtotal_paise,shipping_paise,total_paise,pickup_location)
            values(:company,:shopper,:key,:hash,'cancelled',cast(:items as jsonb),'{}',100,0,100,'') returning id"""),
            params).scalar_one()
        with self.assertRaises(HTTPException) as used:
            self.service.delete_product(self.product_id)
        self.assertEqual(used.exception.status_code, 409)
        self.db.execute(self.text("delete from shop_orders where id=:id"), {"id": order})
        first_store = self.db.execute(self.text("select id from stores where company_id=:company and is_default"),
                                      {"company": self.company}).scalar_one()
        second_store = self.db.execute(self.text("""insert into stores(company_id,code,name,kind,holds_stock,state_code)
            values(:company,'SECOND','Other stock room','warehouse',true,'33') returning id"""),
            {"company": self.company}).scalar_one()
        self.db.execute(self.text("""insert into stock_transfers(company_id,from_store_id,to_store_id,notes,lines)
            values(:company,:first,:second,'Historical fixture',cast(:lines as jsonb))"""),
            {"company": self.company, "first": first_store, "second": second_store,
             "lines": json.dumps([{"product_id": self.product_id, "quantity": 1}])})
        with self.assertRaises(HTTPException) as used:
            self.service.delete_product(self.product_id)
        self.assertEqual(used.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()