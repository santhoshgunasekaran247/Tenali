import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import shop
from app.schemas.checkout import CheckoutInput, CheckoutSettingsInput, DispatchInput, PackageInput
from app.services import checkout_providers, shop_checkout, shop_orders_service


RAZORPAY = {"razorpay_key_id": "rzp_live_fixture", "razorpay_key_secret": "fixture",
            "razorpay_webhook_secret": "fixture-webhook-secret"}


class SelfShippingTests(unittest.TestCase):
    def test_public_and_admin_checkout_status_share_online_store_readiness(self):
        for enabled, online_ready in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(enabled=enabled, online_ready=online_ready):
                settings = {**CheckoutSettingsInput(shipping_provider="self", shipping_paise=0,
                    enabled=enabled).model_dump(), "credentials": "encrypted"}
                db = MagicMock()
                db.execute.return_value.mappings.return_value.first.return_value = settings
                db.execute.return_value.mappings.return_value.__iter__.return_value = iter([])
                with patch.object(shop_checkout, "find_online_store", return_value={"id": "online"} if online_ready else None), \
                        patch.object(shop.providers, "decrypt_credentials", return_value=RAZORPAY), \
                        patch.object(shop.orders_service, "whatsapp_number", return_value=None):
                    company_id = str(uuid4())
                    public = shop.availability({"id": company_id}, db)
                    admin = shop.read_settings({"company_id": company_id}, db)
                self.assertEqual(public["enabled"], enabled and online_ready)
                self.assertEqual(admin["checkout_available"], public["enabled"])
                self.assertEqual(admin["checkout_blocker"], public["disabled_reason"])
                self.assertEqual(admin["online_store_ready"], online_ready)
                self.assertEqual(admin["payment_mode"], "live")
                if enabled and not online_ready:
                    self.assertIn("fulfilment warehouse", admin["checkout_blocker"])

    def test_readiness_uses_the_same_warehouse_requirements_as_order_creation(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.first.return_value = None
        result = shop_checkout.checkout_availability(db, "company", {"enabled": True})
        self.assertFalse(result["enabled"])
        sql = str(db.execute.call_args.args[0])
        for condition in ("o.kind='online'", "o.is_active", "w.is_active", "w.holds_stock",
                          "w.id=o.fulfilment_store_id", "o.company_id=:company"):
            self.assertIn(condition, sql)
        with self.assertRaises(HTTPException):
            shop_checkout.online_store(db, "company")
        result = shop_checkout.checkout_availability(db, "company", None)
        self.assertFalse(result["enabled"])
        self.assertIn("not been set up", result["disabled_reason"])

    def test_self_shipping_settings_need_only_enabled_payment_credentials(self):
        for prepaid in (True, False):
            db = MagicMock()
            db.execute.return_value.scalar_one_or_none.return_value = None
            payload = CheckoutSettingsInput(shipping_provider="self", enabled=True, shipping_paise=100,
                prepaid_enabled=prepaid, cod_enabled=not prepaid, **(RAZORPAY if prepaid else {}))
            identity = {"company_id": str(uuid4()), "user_id": str(uuid4())}
            with patch.object(shop, "TenantAuth"), patch.object(shop.providers, "encrypt_credentials", return_value="encrypted") as encrypt:
                self.assertEqual(shop.save_settings(payload, identity, db), {"saved": True})
            saved = db.execute.call_args_list[-1].args[1]
            self.assertEqual(saved["shipping_provider"], "self")
            self.assertEqual(saved["company"], identity["company_id"])
            if prepaid:
                self.assertEqual(encrypt.call_args.args[1], RAZORPAY)
            else:
                encrypt.assert_not_called()
                self.assertEqual(saved["credentials"], "")
            db.commit.assert_called_once()

    def test_provider_credentials_remain_paired_and_payment_cannot_be_bypassed(self):
        for values in (
            {"shipping_provider": "self"},
            {"shipping_provider": "self", "razorpay_key_id": "rzp_live_fixture"},
            {"shipping_provider": "shiprocket", **RAZORPAY},
            {"shipping_provider": "self", **RAZORPAY, "shiprocket_email": "api@example.invalid"},
        ):
            with self.subTest(values=list(values)):
                db = MagicMock()
                db.execute.return_value.scalar_one_or_none.return_value = None
                with self.assertRaises(HTTPException) as error:
                    shop.save_settings(CheckoutSettingsInput(shipping_paise=0, **values),
                                       {"company_id": str(uuid4()), "user_id": str(uuid4())}, db)
                self.assertEqual(error.exception.status_code, 422)
                db.commit.assert_not_called()
        with self.assertRaises(ValidationError):
            CheckoutSettingsInput(shipping_provider="unknown", shipping_paise=0)

    def test_switching_shipping_keeps_existing_encrypted_credentials(self):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = "existing"
        credentials = {**RAZORPAY, "shiprocket_email": "api@example.invalid", "shiprocket_password": "fixture"}
        with patch.object(shop, "TenantAuth"), \
                patch.object(shop.providers, "decrypt_credentials", return_value=credentials.copy()), \
                patch.object(shop.providers, "encrypt_credentials", return_value="retained") as encrypt:
            shop.save_settings(CheckoutSettingsInput(shipping_provider="self", shipping_paise=0),
                               {"company_id": str(uuid4()), "user_id": str(uuid4())}, db)
        self.assertEqual(encrypt.call_args.args[1], credentials)
        self.assertFalse(any("update shop_orders" in str(call.args[0]) for call in db.execute.call_args_list))

    def test_settings_read_reports_self_shipping_without_shiprocket_or_false_live_mode(self):
        for credentials in ({}, RAZORPAY, {"shiprocket_email": "api@example.invalid", "shiprocket_password": "fixture"}):
            payload = CheckoutSettingsInput(shipping_provider="self", shipping_paise=0).model_dump()
            db = MagicMock()
            db.execute.return_value.mappings.return_value.first.return_value = {
                **payload, "credentials": "encrypted" if credentials else ""}
            with patch.object(shop.providers, "decrypt_credentials", return_value=credentials):
                result = shop.read_settings({"company_id": str(uuid4())}, db)
            self.assertEqual(result["shipping_provider"], "self")
            self.assertEqual(result["payment_mode"], "live" if "razorpay_key_id" in credentials else None)
            self.assertEqual(result["razorpay_saved"], bool(credentials.get("razorpay_key_id")))
            self.assertNotIn("credentials", result)

    def test_self_shipped_orders_cannot_call_shiprocket(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.first.return_value = {
            "shipping_provider": "self", "status": "paid"}
        package = PackageInput(weight=1, length=10, width=10, height=10)
        with patch.object(checkout_providers, "provider_request") as provider:
            for operation in (
                lambda: shop_checkout.create_shipment(db, MagicMock(), str(uuid4()), str(uuid4()), package),
                lambda: shop_checkout.reconcile_shipment(db, str(uuid4()), str(uuid4()), 123),
            ):
                with self.assertRaises(HTTPException) as error:
                    operation()
                self.assertEqual(error.exception.status_code, 409)
            provider.assert_not_called()
        db.commit.assert_not_called()

    def test_missing_optional_provider_credentials_return_configuration_error(self):
        with patch.object(checkout_providers, "provider_request") as provider:
            with self.assertRaises(HTTPException) as error:
                checkout_providers.check_connection("shiprocket", RAZORPAY, "")
            self.assertEqual(error.exception.status_code, 409)
            provider.assert_not_called()

    def test_existing_shiprocket_orders_keep_test_payment_guard_and_booking_idempotency(self):
        self.assertEqual(CheckoutSettingsInput(shipping_paise=0).shipping_provider, "shiprocket")
        db = MagicMock()
        package = PackageInput(weight=1, length=10, width=10, height=10)
        row = {"shipping_provider": "shiprocket", "status": "paid", "fulfilment_method": "delivery",
               "payment_method": "prepaid", "provider_key_id": "rzp_test_fixture"}
        db.execute.return_value.mappings.return_value.first.return_value = row
        with patch.object(checkout_providers, "provider_request") as provider, \
                patch.object(shop_checkout, "public_order", side_effect=lambda value: value):
            with self.assertRaises(HTTPException) as error:
                shop_checkout.create_shipment(db, MagicMock(), str(uuid4()), str(uuid4()), package)
            self.assertIn("test payment", error.exception.detail)
            row["status"] = "shipment_booked"
            self.assertEqual(shop_checkout.create_shipment(db, MagicMock(), str(uuid4()), str(uuid4()), package), row)
            provider.assert_not_called()

    def test_new_orders_snapshot_shipping_choice_and_retry_does_not_change_it(self):
        for method in ("cod", "prepaid"):
            db, identity_db = MagicMock(), MagicMock()
            db.execute.return_value.mappings.return_value.first.return_value = None
            payload = CheckoutInput(request_key=uuid4(), items=[{"product_id": uuid4(), "quantity": 1}],
                address={"name": "Fixture", "phone": "9876543210", "address": "123 Fixture Street",
                         "city": "Chennai", "state": "Tamil Nadu", "pincode": "600001"},
                payment_method=method, expected_total_paise=11000)
            settings = {**CheckoutSettingsInput(shipping_provider="self", shipping_paise=1000).model_dump(), "credentials": "encrypted"}
            quote = {"items": [{"unit_paise": 10000, "quantity": 1}], "subtotal_paise": 10000, "shipping_paise": 1000,
                     "total_paise": 11000, "store": {"id": uuid4()}, "pickup": None}
            company = str(uuid4())
            with patch.object(shop_checkout, "settings_for", return_value=settings), \
                    patch.object(shop_checkout, "quote_order", return_value=quote), \
                    patch.object(shop_checkout, "public_order", side_effect=lambda row: row), \
                    patch.object(checkout_providers, "decrypt_credentials", return_value=RAZORPAY), \
                    patch.object(checkout_providers, "provider_request", return_value={"id": "order_fixture", "amount": 11000, "currency": "INR"}) as provider:
                shop_checkout.create_order(db, identity_db, company, str(uuid4()), payload)
                saved = db.execute.call_args.args[1]
                self.assertEqual(saved["shipping_provider"], "self")
                self.assertEqual(saved["company"], company)
                self.assertEqual(saved["shipping"], 1000)
                self.assertTrue(all(call.args[0] == "razorpay" for call in provider.call_args_list))
                if method == "cod":
                    provider.assert_not_called()
                db.execute.return_value.mappings.return_value.first.return_value = {
                    "request_hash": saved["hash"], "shipping_provider": "self"}
                settings["shipping_provider"] = "shiprocket"
                replay = shop_checkout.create_order(db, identity_db, company, str(uuid4()), payload)
                self.assertEqual(replay["shipping_provider"], "self")

    def test_self_shipping_dispatch_saves_tracking_and_uses_existing_invoice_flow_once(self):
        company, order_id, store_id = str(uuid4()), str(uuid4()), str(uuid4())
        order = {"id": order_id, "status": "confirmed", "payment_method": "cod", "invoice_id": None,
                 "store_id": store_id, "shipping_provider": "self", "fulfilment_method": "delivery",
                 "address": {"state": "Tamil Nadu"}}
        db = MagicMock()
        with patch.object(shop_orders_service, "_order", return_value=order), \
                patch.object(shop_orders_service, "_order_out", return_value={"status": "dispatched"}), \
                patch.object(shop_orders_service, "get_store", return_value={"fulfilment_store_id": store_id}), \
                patch.object(shop_orders_service, "stock_store", return_value={"id": store_id}), \
                patch.object(shop_orders_service, "_create_order_invoice", return_value={"id": str(uuid4())}) as invoice, \
                patch.object(checkout_providers, "provider_request") as provider:
            result = shop_orders_service.dispatch_order(db, company, order_id,
                DispatchInput(courier="Own courier", awb="TRACK-1"))
            self.assertEqual(result["status"], "dispatched")
            update = db.execute.call_args_list[0].args[1]
            self.assertEqual((update["courier"], update["awb"], update["company"]), ("Own courier", "TRACK-1", company))
            self.assertEqual(invoice.call_args.kwargs["amount_received"], Decimal("0"))
            order["invoice_id"] = "saved"
            shop_orders_service.dispatch_order(db, company, order_id, DispatchInput())
            invoice.assert_called_once()
            provider.assert_not_called()
            db.commit.assert_called_once()

    def test_shiprocket_delivery_orders_cannot_be_dispatched_before_shiprocket_booking(self):
        order = {"id": str(uuid4()), "status": "paid", "invoice_id": None, "shipping_provider": "shiprocket",
                 "payment_method": "prepaid", "advance_transaction_id": str(uuid4()), "review_reason": None,
                 "fulfilment_method": "delivery", "shiprocket_order_id": None}
        db = MagicMock()
        with patch.object(shop_orders_service, "_order", return_value=order), \
                patch.object(shop_orders_service, "_create_order_invoice") as invoice:
            with self.assertRaises(HTTPException) as error:
                shop_orders_service.dispatch_order(db, str(uuid4()), order["id"], DispatchInput())
            self.assertEqual(error.exception.status_code, 409)
            self.assertIn("Submit this order to Shiprocket", error.exception.detail)
            invoice.assert_not_called()
            db.commit.assert_not_called()

    def _late_shipment(self, row, shipment):
        db, identity_db = MagicMock(), MagicMock()
        db.execute.return_value.mappings.return_value.first.return_value = row
        db.execute.return_value.mappings.return_value.one.return_value = {**row, "shiprocket_order_id": 991}
        identity_db.execute.return_value.scalar_one.return_value = "shopper@example.invalid"
        responses = [{"token": "token"}, shipment]
        with patch.object(checkout_providers, "provider_request", side_effect=lambda *args, **kwargs: responses.pop(0)) as provider, \
                patch.object(checkout_providers, "decrypt_credentials", return_value={"shiprocket_email": "a@b.invalid", "shiprocket_password": "x"}), \
                patch.object(checkout_providers, "encrypt_credentials", return_value="encrypted"), \
                patch.object(shop_checkout, "public_order", side_effect=lambda value: value):
            result = shop_checkout.create_shipment(db, identity_db, str(uuid4()), str(row["id"]),
                                                   PackageInput(weight=1, length=10, width=10, height=10))
        return db, provider, result

    def _dispatched_row(self, **extra):
        from datetime import datetime
        return {"id": uuid4(), "shipping_provider": "shiprocket", "status": "dispatched", "fulfilment_method": "delivery",
                "payment_method": "prepaid", "provider_key_id": "rzp_live_fixture", "shiprocket_order_id": None,
                "shipping_error": None, "credentials": "encrypted", "shopper_id": uuid4(), "pickup_location": "Primary",
                "created_at": datetime(2026, 1, 1), "subtotal_paise": 10000, "shipping_paise": 0,
                "address": {"name": "A", "address": "1 St", "city": "Chennai", "pincode": "600001", "state": "Tamil Nadu", "phone": "9999999999"},
                "items": [{"name": "Item", "sku": "SKU", "quantity": 1, "unit_paise": 10000}], **extra}

    def test_dispatched_orders_without_shiprocket_booking_can_be_submitted_without_changing_status(self):
        for status in ("dispatched", "delivered"):
            db, provider, result = self._late_shipment(self._dispatched_row(status=status), {"order_id": 991, "shipment_id": 552})
            self.assertEqual(result["shiprocket_order_id"], 991)
            self.assertEqual(provider.call_count, 2)
            updates = [call.args[1] for call in db.execute.call_args_list if "update shop_orders" in str(call.args[0])]
            self.assertEqual((updates[0]["status"], updates[0]["late"]), ("dispatched", True))
            self.assertIn("in progress", updates[0]["marker"])
            self.assertEqual(updates[-1]["status"], "dispatched")
            self.assertIsNone(updates[-1].get("marker"))

    def test_orders_without_shiprocket_booking_cannot_be_marked_delivered(self):
        order = {"fulfilment_method": "delivery", "status": "dispatched", "shipping_provider": "shiprocket", "shiprocket_order_id": None}
        db = MagicMock()
        with patch.object(shop_orders_service, "_order", return_value=order):
            with self.assertRaises(HTTPException) as error:
                shop_orders_service.mark_delivered(db, str(uuid4()), str(uuid4()))
        self.assertIn("Submit this order to Shiprocket", error.exception.detail)
        db.commit.assert_not_called()

    def test_recovery_of_unbooked_delivered_order_uses_workspace_credentials_and_reverts_to_dispatched(self):
        row = self._dispatched_row(status="delivered", credentials=None)
        db, identity_db = MagicMock(), MagicMock()
        db.execute.return_value.mappings.return_value.first.return_value = row
        db.execute.return_value.mappings.return_value.one.return_value = row
        responses = [{"token": "token"}, {"data": {"channel_order_id": str(row["id"]), "shipments": [{"id": 552, "awb": "AWB1"}]}}]
        with patch.object(checkout_providers, "provider_request", side_effect=lambda *args, **kwargs: responses.pop(0)), \
                patch.object(shop_checkout, "settings_for", return_value={"credentials": "workspace"}) as settings, \
                patch.object(checkout_providers, "decrypt_credentials", return_value={"shiprocket_email": "a@b.invalid", "shiprocket_password": "x"}), \
                patch.object(shop_checkout, "public_order", side_effect=lambda value: value):
            shop_checkout.reconcile_shipment(db, str(uuid4()), str(row["id"]), 991, identity_db)
        settings.assert_called_once()
        update = next(call.args[1] for call in db.execute.call_args_list if "update shop_orders" in str(call.args[0]))
        self.assertEqual((update["status"], update["late"], update["provider"], update["awb"]), ("dispatched", True, 991, "AWB1"))

    def test_dispatched_orders_with_unconfirmed_or_existing_shiprocket_booking_are_not_resubmitted(self):
        for extra in ({"shipping_error": "Provider response uncertain"}, {"shiprocket_order_id": 991}):
            row = self._dispatched_row(**extra)
            db = MagicMock()
            db.execute.return_value.mappings.return_value.first.return_value = row
            with patch.object(checkout_providers, "provider_request") as provider, \
                    patch.object(shop_checkout, "public_order", side_effect=lambda value: value):
                if extra.get("shiprocket_order_id"):
                    self.assertEqual(shop_checkout.create_shipment(db, MagicMock(), str(uuid4()), str(uuid4()),
                                                                   PackageInput(weight=1, length=10, width=10, height=10)), row)
                else:
                    with self.assertRaises(HTTPException) as error:
                        shop_checkout.create_shipment(db, MagicMock(), str(uuid4()), str(uuid4()),
                                                      PackageInput(weight=1, length=10, width=10, height=10))
                    self.assertIn("recover", error.exception.detail)
                provider.assert_not_called()
                db.commit.assert_not_called()

    def test_manual_tracking_cannot_override_shiprocket_or_bypass_payment(self):
        for shipping, payment, advance in (("shiprocket", "cod", None), ("self", "prepaid", None)):
            db = MagicMock()
            order = {"status": "paid" if payment == "prepaid" else "confirmed", "invoice_id": None,
                     "shipping_provider": shipping, "payment_method": payment, "advance_transaction_id": advance,
                     "review_reason": None, "fulfilment_method": "delivery"}
            with patch.object(shop_orders_service, "_order", return_value=order), \
                    patch.object(shop_orders_service, "_create_order_invoice") as invoice:
                with self.assertRaises(HTTPException):
                    shop_orders_service.dispatch_order(db, str(uuid4()), str(uuid4()), DispatchInput(awb="TRACK"))
                invoice.assert_not_called()
                db.commit.assert_not_called()
