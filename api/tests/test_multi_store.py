import os
import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only multi-store tests")
class MultiStoreTests(unittest.TestCase):
    def setUp(self):
        from dotenv import load_dotenv
        from sqlalchemy import text
        from sqlalchemy.orm import Session

        load_dotenv("api/.env")
        from app.core.database import engine
        from app.schemas.accounts import AccountCreate
        from app.schemas.inventory import ProductInput, StockAdjustment, VendorOfferInput
        from app.schemas.masters import HsnMasterCreate
        from app.schemas.stores import StoreInput
        from app.services.accounts_service import AccountsService
        from app.services.inventory_service import InventoryService
        from app.services.masters_service import MastersService
        from app.services.stores_service import StoresService
        from schema_support import ensure_default_store

        self.text = text
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        self.company, self.party, self.shopper = (str(uuid4()) for _ in range(3))
        self.db.execute(text("""insert into companies(id, company_name, address, gst_number, whatsapp_number)
            values(:id, 'Multi-store regression', 'Chennai', '33ABCDE1234F1Z5', '+919000000001')"""), {"id": self.company})
        self.main = ensure_default_store(self.db, self.company)
        self.db.execute(text("""insert into parties(id, company_id, party_type, legal_name, system_role)
            values(:id, :company, 'customer', 'Online shopper', 'online_shopper')"""), {"id": str(uuid4()), "company": self.company})
        self.db.execute(text("""insert into parties(id, company_id, party_type, legal_name, address)
            values(:id, :company, 'customer_vendor', 'Vendor and customer', 'Chennai')"""), {"id": self.party, "company": self.company})
        self.db.execute(text("""insert into shopper_accounts(id, company_id, email, display_name, password_hash)
            values(:id, :company, :email, 'Shopper', 'x')"""), {"id": self.shopper, "company": self.company, "email": uuid4().hex + "@example.invalid"})
        self.db.execute(text("""insert into checkout_settings(company_id, enabled, credentials, shipping_paise, pickup_location,
            prepaid_enabled, cod_enabled, pickup_enabled, cod_limit) values(:company, true, '', 5000, '', false, true, true, 20000)"""), {"company": self.company})
        self.accounts = AccountsService(self.db)
        self.bank = self.accounts.create_account(self.company, AccountCreate(nickname="Bank", account_type="bank", is_company_account=True))
        self.clearing = self.accounts.create_account(self.company, AccountCreate(nickname="Razorpay clearing", account_type="other"))
        self.cod_clearing = self.accounts.create_account(self.company, AccountCreate(nickname="COD clearing", account_type="other"))
        stores = StoresService(self.db, self.company)
        self.shop = stores.create_store(StoreInput(code="T2", name="Second shop", kind="offline", allows_pickup=True,
                                                    state_code="33", pincode="600002", latitude=13.05, longitude=80.25,
                                                    whatsapp_number="+919000000002", address="Chennai 2"))
        self.web = stores.create_store(StoreInput(code="WEB", name="Online", kind="online", fulfilment_store_id=self.main,
                                                   settlement_account_id=self.clearing["id"]))
        self.shop["id"], self.web["id"] = str(self.shop["id"]), str(self.web["id"])
        MastersService(self.db).create_hsn(HsnMasterCreate(code="8516", description="Test", gst_rate=18), self.company)
        self.inventory = InventoryService(self.db, self.company)
        product = self.inventory.save_product(ProductInput(name="Kettle", hsn_code="8516", selling_price=1180, catalog_visible=True))
        self.product = str(product["id"])
        self.inventory.save_offer(self.product, VendorOfferInput(vendor_id=self.party, mrp=1500, buying_price=800))
        self.inventory.adjust_stock(self.product, StockAdjustment(direction="IN", quantity=10, notes="Opening", store_id=self.main))

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def stock(self, store_id):
        return self.db.execute(self.text("""select coalesce(sum(quantity),0) from stock_balances
            where company_id=:company and store_id=:store and product_id=:product"""),
            {"company": self.company, "store": store_id, "product": self.product}).scalar_one()

    def order(self, payment_method, fulfilment_method="delivery", pickup_store_id=None, quantity=2):
        from app.schemas.checkout import CheckoutInput
        from app.services.shop_checkout import create_order

        payload = CheckoutInput(request_key=uuid4(), items=[{"product_id": self.product, "quantity": quantity}],
                                address={"name": "Buyer", "phone": "9876543210", "address": "12 Beach Road", "city": "Chennai",
                                         "state": "Tamil Nadu", "pincode": "600001"},
                                payment_method=payment_method, fulfilment_method=fulfilment_method, pickup_store_id=pickup_store_id,
                                expected_total_paise=quantity * 118000 + (0 if fulfilment_method == "pickup" else 5000))
        return create_order(self.db, self.db, self.company, self.shopper, payload)

    def test_per_store_stock_transfer_and_negative_guard(self):
        from app.schemas.inventory import StockAdjustment, StockTransferCreate

        with self.assertRaises(HTTPException) as error:
            self.inventory.adjust_stock(self.product, StockAdjustment(direction="OUT", quantity=1, notes="x", store_id=self.shop["id"]))
        self.assertEqual(error.exception.status_code, 422)
        transfer = self.inventory.transfer_stock(StockTransferCreate(from_store_id=self.main, to_store_id=self.shop["id"], notes="Stock up shop",
                                                                     lines=[{"product_id": self.product, "quantity": 4}]))
        self.assertEqual((self.stock(self.main), self.stock(self.shop["id"])), (Decimal("6"), Decimal("4")))
        movements = self.db.execute(self.text("""select store_id, movement_type from stock_movements where reference_type='stock_transfer'
            and reference_id=:id order by movement_type"""), {"id": transfer["id"]}).all()
        self.assertEqual([(str(s), t) for s, t in movements], [(self.shop["id"], "TRANSFER_IN"), (self.main, "TRANSFER_OUT")])
        with self.assertRaises(HTTPException):
            self.inventory.transfer_stock(StockTransferCreate(from_store_id=self.shop["id"], to_store_id=self.main, notes="Too much",
                                                              lines=[{"product_id": self.product, "quantity": 5}]))
        reversed_transfer = self.inventory.reverse_transfer(str(transfer["id"]), "Sent by mistake")
        self.assertEqual(str(reversed_transfer["reversal_of_transfer_id"]), str(transfer["id"]))
        self.assertEqual((self.stock(self.main), self.stock(self.shop["id"])), (Decimal("10"), Decimal("0")))
        with self.assertRaises(HTTPException):
            self.inventory.reverse_transfer(str(transfer["id"]), "Again")
        rows = self.inventory.stock_reconciliation()["items"]
        self.assertTrue(all(row["difference"] == 0 for row in rows))
        self.assertEqual({row["store_code"] for row in rows}, {"MAIN", "T2"})

    def test_store_numbering_and_inclusive_billing(self):
        from app.schemas.billing import InvoiceCreate
        from app.schemas.purchases import PurchaseCreate
        from app.services.billing_service import BillingService
        from app.services.purchases_service import PurchasesService

        billing = BillingService(self.db)
        first = billing.create_invoice(self.company, InvoiceCreate(customer_party_id=self.party, place_of_supply="33 - Tamil Nadu",
            invoice_date=date(2026, 10, 5), lines=[{"product_id": self.product, "description": "x", "hsn": "8516", "quantity": 1, "rate": 1180}]))
        second = billing.create_invoice(self.company, InvoiceCreate(customer_party_id=self.party, store_id=self.shop["id"], place_of_supply="33 - Tamil Nadu",
            invoice_date=date(2026, 10, 5), subtotal=100))
        self.assertEqual(first["invoice_number"], "INV-MAIN-202610-00001")
        self.assertEqual(second["invoice_number"], "INV-T2-202610-00001")
        self.assertEqual((first["subtotal"], first["gst_total"], first["total"]), (Decimal("1000.00"), Decimal("180.00"), Decimal("1180.00")))
        self.assertEqual(self.stock(self.main), Decimal("9"))
        purchase = PurchasesService(self.db).create_purchase(self.company, PurchaseCreate(vendor_party_id=self.party, store_id=self.shop["id"],
            purchase_date=date(2026, 10, 6), bill_number="V-77", lines=[{"product_id": self.product, "description": "x", "hsn": "8516", "quantity": 3, "rate": 800}]))
        self.assertEqual(purchase["voucher_number"], "PUR-T2-202610-00001")
        self.assertEqual((purchase["subtotal"], purchase["gst_total"]), (Decimal("2400.00"), Decimal("432.00")))
        from app.schemas.purchases import PurchaseReceiptConfirm
        PurchasesService(self.db).confirm_purchase_receipt(str(purchase["id"]), self.company, PurchaseReceiptConfirm())
        self.assertEqual((self.stock(self.main), self.stock(self.shop["id"])), (Decimal("9"), Decimal("3")))

    def test_cod_request_approve_dispatch_and_settlement(self):
        from app.schemas.checkout import CodSettlementInput, DispatchInput
        from app.services import shop_orders_service as service

        order = self.order("cod")
        self.assertEqual(order["status"], "cod_requested")
        self.assertEqual(self.inventory.available_stock(self.main, self.product, None), Decimal("10"))
        with self.assertRaises(HTTPException):
            service.dispatch_order(self.db, self.company, str(order["id"]), DispatchInput())
        approved = service.approve_cod(self.db, self.company, str(order["id"]))
        self.assertEqual(approved["status"], "confirmed")
        self.assertEqual(self.inventory.available_stock(self.main, self.product, None), Decimal("8"))
        dispatched = service.dispatch_order(self.db, self.company, str(order["id"]), DispatchInput(ship_from_store_id=self.main))
        self.assertEqual(dispatched["status"], "dispatched")
        invoice = self.db.execute(self.text("select invoice_number, total, collection_status, store_id from invoices where id=:id"),
                                  {"id": dispatched["invoice_id"]}).mappings().one()
        self.assertTrue(invoice["invoice_number"].startswith("INV-WEB-"))
        self.assertEqual((invoice["total"], invoice["collection_status"], str(invoice["store_id"])), (Decimal("2410.00"), "UNPAID", self.web["id"]))
        self.assertEqual(self.stock(self.main), Decimal("8"))
        outstanding = service.cod_outstanding(self.db, self.company)
        self.assertEqual(outstanding["total_outstanding"], Decimal("2410.00"))
        with self.assertRaises(HTTPException):
            service.record_cod_settlement(self.db, self.company, CodSettlementInput(courier="Delhivery", settlement_reference="UTR1",
                settlement_date=date.today(), account_id=self.cod_clearing["id"], items=[{"order_id": order["id"], "amount": "2300.00"}]))
        settlement = service.record_cod_settlement(self.db, self.company, CodSettlementInput(courier="Delhivery", settlement_reference="UTR1",
            settlement_date=date.today(), account_id=self.cod_clearing["id"], items=[{"order_id": order["id"], "amount": "2300.00"}],
            shortfall_reason="Courier COD handling fee 110"))
        self.assertEqual((settlement["expected_amount"], settlement["received_amount"]), (Decimal("2410.00"), Decimal("2300.00")))
        state = self.db.execute(self.text("select collection_status, amount_received from invoices where id=:id"),
                                {"id": dispatched["invoice_id"]}).mappings().one()
        self.assertEqual((state["collection_status"], state["amount_received"]), ("PARTIAL", Decimal("2300.00")))
        self.assertEqual(service.cod_outstanding(self.db, self.company)["total_outstanding"], Decimal("110.00"))
        with self.assertRaises(HTTPException):
            service.record_cod_settlement(self.db, self.company, CodSettlementInput(courier="Delhivery", settlement_reference="UTR1",
                settlement_date=date.today(), account_id=self.cod_clearing["id"], items=[{"order_id": order["id"], "amount": "110.00"}]))

    def test_manual_customer_link_only_affects_future_order_invoices(self):
        from app.schemas.checkout import DispatchInput
        from app.services import shop_orders_service as service

        first = self.order("cod", quantity=1)
        service.approve_cod(self.db, self.company, str(first["id"]))
        before = service.dispatch_order(self.db, self.company, str(first["id"]), DispatchInput(ship_from_store_id=self.main))
        old_party = self.db.execute(self.text("select customer_party_id from invoices where id=:id"),
                                    {"id": before["invoice_id"]}).scalar_one()
        self.db.execute(self.text("update shopper_accounts set customer_party_id=:party where company_id=:company and id=:id"),
                        {"party": self.party, "company": self.company, "id": self.shopper})
        self.db.commit()
        second = self.order("cod", quantity=1)
        service.approve_cod(self.db, self.company, str(second["id"]))
        after = service.dispatch_order(self.db, self.company, str(second["id"]), DispatchInput(ship_from_store_id=self.main))
        self.assertEqual(str(self.db.execute(self.text("select customer_party_id from invoices where id=:id"),
                                             {"id": after["invoice_id"]}).scalar_one()), self.party)
        self.assertEqual(self.db.execute(self.text("select customer_party_id from invoices where id=:id"),
                                         {"id": before["invoice_id"]}).scalar_one(), old_party)
        self.assertNotEqual(str(old_party), self.party)

    def test_pay_at_pickup_reserves_shop_stock_and_invoices_in_shop_series(self):
        from app.schemas.checkout import CollectInput
        from app.schemas.inventory import StockTransferCreate
        from app.services import shop_orders_service as service

        with self.assertRaises(HTTPException):
            self.order("pay_at_pickup", "pickup", self.shop["id"])
        self.inventory.transfer_stock(StockTransferCreate(from_store_id=self.main, to_store_id=self.shop["id"], notes="Stock shop",
                                                          lines=[{"product_id": self.product, "quantity": 3}]))
        nearby = service.nearby_availability(self.db, self.company, self.product, None, 13.05, 80.25, None)
        self.assertEqual([(item["code"], item["availability"], item["whatsapp_number"]) for item in nearby["items"]],
                         [("T2", "available", "+919000000002")])
        order = self.order("pay_at_pickup", "pickup", self.shop["id"])
        self.assertEqual((order["status"], order["shipping_paise"]), ("confirmed", 0))
        self.assertEqual(self.inventory.available_stock(self.shop["id"], self.product, None), Decimal("1"))
        self.assertEqual(service.nearby_availability(self.db, self.company, self.product, None, None, None, "600002")["items"][0]["availability"], "few_left")
        with self.assertRaises(HTTPException):
            service.collect_pickup(self.db, self.company, str(order["id"]), CollectInput())
        collected = service.collect_pickup(self.db, self.company, str(order["id"]), CollectInput(account_id=self.bank["id"], payment_mode="upi"))
        self.assertEqual(collected["status"], "collected")
        invoice = self.db.execute(self.text("select invoice_number, collection_status, amount_received, store_id from invoices where id=:id"),
                                  {"id": collected["invoice_id"]}).mappings().one()
        self.assertTrue(invoice["invoice_number"].startswith("INV-T2-"))
        self.assertEqual((invoice["collection_status"], invoice["amount_received"], str(invoice["store_id"])), ("SETTLED", Decimal("2360.00"), self.shop["id"]))
        self.assertEqual((self.stock(self.shop["id"]), self.stock(self.main)), (Decimal("1"), Decimal("7")))

    def test_expired_holds_release_stock_and_cancel_refunds_advance(self):
        from app.schemas.checkout import OrderCancel
        from app.services import shop_orders_service as service

        order = self.order("cod", quantity=10)
        service.approve_cod(self.db, self.company, str(order["id"]))
        self.assertEqual(self.inventory.available_stock(self.main, self.product, None), Decimal("0"))
        self.db.execute(self.text("update shop_orders set expires_at=now()-interval '1 minute' where id=:id"), {"id": order["id"]})
        self.assertEqual(self.inventory.available_stock(self.main, self.product, None), Decimal("10"))
        self.assertEqual(service.expire_orders(self.db, self.company), 1)
        prepaid = self.order("cod", quantity=1)
        service.approve_cod(self.db, self.company, str(prepaid["id"]))
        cancelled = service.cancel_order(self.db, self.company, str(prepaid["id"]), OrderCancel(reason="Customer changed mind"))
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.inventory.available_stock(self.main, self.product, None), Decimal("10"))
        simulated = self.order("cod", quantity=1)
        self.db.execute(self.text("""update shop_orders set status='paid', payment_method='prepaid', razorpay_payment_id='pay_test'
            where id=:id"""), {"id": simulated["id"]})
        service.post_prepaid_advance(self.db, self.company, dict(self.db.execute(self.text("select * from shop_orders where id=:id"),
                                                                             {"id": simulated["id"]}).mappings().one()))
        with self.assertRaises(HTTPException):
            service.cancel_order(self.db, self.company, str(simulated["id"]), OrderCancel(reason="No refund account"))
        refunded = service.cancel_order(self.db, self.company, str(simulated["id"]),
                                        OrderCancel(reason="Out of stock", refund_account_id=self.clearing["id"]))
        self.assertEqual(refunded["status"], "refunded")
        balance = self.db.execute(self.text("""select coalesce(sum(case when to_account_id=:account then amount else -amount end),0)
            from account_transactions where company_id=:company and (to_account_id=:account or from_account_id=:account)"""),
            {"company": self.company, "account": self.clearing["id"]}).scalar_one()
        self.assertEqual(balance, Decimal("0"))

    def test_store_rules(self):
        from app.schemas.stores import StoreInput
        from app.services.stores_service import StoresService

        stores = StoresService(self.db, self.company)
        with self.assertRaises(HTTPException):
            stores.update_store(self.main, StoreInput(code="MAIN", name="Main store", kind="offline", is_active=False))
        with self.assertRaises(HTTPException):
            stores.set_default(self.web["id"])
        with self.assertRaises(HTTPException):
            stores.update_store(self.main, StoreInput(code="MAIN", name="Main store", kind="warehouse"))
        with self.assertRaises(HTTPException):
            stores.create_store(StoreInput(code="T2", name="Duplicate", kind="offline"))
        closed = stores.update_store(self.shop["id"], StoreInput(code="T2", name="Second shop", kind="offline", is_active=False))
        self.assertFalse(closed["is_active"])

    def test_unregistered_business_issues_bill_of_supply_without_gstin(self):
        from app.schemas.billing import InvoiceCreate
        from app.services.billing_service import BillingService

        self.db.execute(self.text("update companies set gst_registered=false, gst_number=null where id=:id"), {"id": self.company})
        invoice = BillingService(self.db).create_invoice(self.company, InvoiceCreate(
            customer_party_id=self.party, place_of_supply="33 - Tamil Nadu", invoice_date=date(2026, 10, 7),
            lines=[{"product_id": self.product, "description": "x", "hsn": "8516", "quantity": 1, "rate": 1180}]))
        self.assertEqual((invoice["subtotal"], invoice["gst_total"], invoice["total"]), (Decimal("1180.00"), Decimal("0.00"), Decimal("1180.00")))
        document = self.db.execute(self.text("select document_data from invoices where id=:id"), {"id": invoice["id"]}).scalar_one()
        self.assertEqual((document["document_title"], document["gst_registered"], document["lines"][0]["gst_rate"]), ("BILL OF SUPPLY", False, "0"))

    def test_store_and_module_access_for_limited_staff(self):
        from app.schemas.billing import InvoiceCreate
        from app.schemas.inventory import StockAdjustment
        from app.services.access import check_module
        from app.services.billing_service import BillingService
        from app.services.stores_service import StoresService, get_store

        billing = BillingService(self.db)
        billing.create_invoice(self.company, InvoiceCreate(customer_party_id=self.party, subtotal=100, invoice_date=date(2026, 10, 8)))
        billing.create_invoice(self.company, InvoiceCreate(customer_party_id=self.party, store_id=self.shop["id"], subtotal=200, invoice_date=date(2026, 10, 8)))
        limited = {"company_id": self.company, "user_id": None, "role": "staff", "store_ids": [self.shop["id"]], "modules": ["billing", "inventory"]}
        self.db.info["tenant_context"] = limited
        try:
            visible = billing.list_invoices(self.company)["items"]
            self.assertEqual([str(item["store_id"]) for item in visible], [self.shop["id"]])
            self.assertEqual([store["code"] for store in StoresService(self.db, self.company).list_stores()["items"]], ["T2"])
            with self.assertRaises(HTTPException) as error:
                get_store(self.db, self.company, self.main)
            self.assertEqual(error.exception.status_code, 403)
            with self.assertRaises(HTTPException):
                self.inventory.adjust_stock(self.product, StockAdjustment(direction="IN", quantity=1, notes="x", store_id=self.main))
            self.assertTrue(all(row["store_code"] == "T2" for row in self.inventory.stock_reconciliation()["items"]))
            with self.assertRaises(HTTPException) as error:
                check_module(limited, "/purchases")
            self.assertEqual(error.exception.status_code, 403)
            check_module(limited, "/billing/invoices")
            check_module({**limited, "role": "admin"}, "/purchases")
        finally:
            self.db.info.pop("tenant_context", None)
