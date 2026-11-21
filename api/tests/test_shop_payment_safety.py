import unittest
from decimal import Decimal
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.checkout import FulfilmentResolutionInput, OrderCancel
from app.services import shop_checkout, shop_orders_service
from app.services.shop_stock import HOLDING_STATUSES


class RefundSafetyTests(unittest.TestCase):
    def setUp(self):
        self.account = uuid4()
        self.order = {"id": "order", "invoice_id": None, "status": "paid", "payment_method": "prepaid",
                      "razorpay_payment_id": "pay_123", "advance_transaction_id": "advance",
                      "total_paise": 12500, "store_id": "online", "shiprocket_order_id": None}
        self.payload = OrderCancel(reason="Out of stock", refund_account_id=self.account,
                                   refund_confirmed=True, refund_reference="rfnd_123")
        self.advance = {"amount": Decimal("125.00"), "source_type": "shop_order", "source_id": "order",
                        "from_account_id": None, "to_account_id": self.account}

    def call(self, *, order=None, advance=None, account=True, duplicate=False, payload=None):
        db = Mock()
        def execute(statement, params):
            sql = str(statement)
            result = Mock()
            if "from account_transactions where id=" in sql:
                result.mappings.return_value.first.return_value = advance if advance is not None else self.advance
            elif "from accounts where" in sql:
                result.scalar_one_or_none.return_value = self.account if account else None
            elif "select 1 from account_transactions" in sql:
                result.first.return_value = (1,) if duplicate else None
            return result
        db.execute.side_effect = execute
        with patch.object(shop_orders_service, "_order", return_value=order or self.order), \
             patch.object(shop_orders_service, "_order_out", return_value={"status": "refunded"}), \
             patch.object(shop_orders_service, "assert_period_open"):
            try:
                result = shop_orders_service.cancel_order(db, "company", "order", payload or self.payload)
                return db, result, None
            except HTTPException as error:
                return db, None, error

    def test_refund_attestation_must_be_complete_and_refund_id_valid(self):
        for values in ({"refund_confirmed": True}, {"refund_reference": "rfnd_123"},
                       {"refund_confirmed": True, "refund_reference": "pay_123"}):
            with self.assertRaises(ValidationError):
                OrderCancel(reason="Reason", **values)

    def test_captured_payment_without_advance_cannot_be_cancelled(self):
        db, _, error = self.call(order={**self.order, "advance_transaction_id": None})
        self.assertEqual(error.status_code, 409)
        db.execute.assert_not_called()
        db.commit.assert_not_called()

    def test_unattested_refund_cannot_be_recorded(self):
        db, _, error = self.call(payload=OrderCancel(reason="Reason", refund_account_id=self.account))
        self.assertEqual(error.status_code, 422)
        db.execute.assert_not_called()
        db.commit.assert_not_called()

    def test_mismatched_advance_inactive_account_and_duplicate_reference_are_rejected(self):
        cases = [
            {"advance": {**self.advance, "source_id": "another"}},
            {"advance": {**self.advance, "amount": Decimal("1.00")}},
            {"account": False},
            {"duplicate": True},
        ]
        for case in cases:
            with self.subTest(case=case):
                db, _, error = self.call(**case)
                self.assertIn(error.status_code, (409, 422))
                self.assertFalse(any("insert into account_transactions" in str(call.args[0]) for call in db.execute.call_args_list))
                db.commit.assert_not_called()

    def test_confirmed_refund_records_provider_reference_and_payment_id_once(self):
        db, result, error = self.call()
        self.assertIsNone(error)
        self.assertEqual(result["status"], "refunded")
        calls = db.execute.call_args_list
        self.assertTrue(any("pg_advisory_xact_lock" in str(call.args[0]) for call in calls))
        insert = next(call for call in calls if "insert into account_transactions" in str(call.args[0]))
        self.assertEqual(insert.args[1]["reference"], "rfnd_123")
        self.assertIn("pay_123", insert.args[1]["description"])
        db.commit.assert_called_once()

    def test_unpaid_cancellation_does_not_create_a_refund(self):
        order = {**self.order, "status": "awaiting_payment", "razorpay_payment_id": None,
                 "advance_transaction_id": None}
        db, _, error = self.call(order=order, payload=OrderCancel(reason="Customer request"))
        self.assertIsNone(error)
        self.assertFalse(any("insert into account_transactions" in str(call.args[0]) for call in db.execute.call_args_list))
        update = next(call for call in db.execute.call_args_list if "update shop_orders" in str(call.args[0]))
        self.assertEqual(update.args[1]["status"], "cancelled")
        db.commit.assert_called_once()

    def test_already_refunded_order_is_not_posted_again(self):
        db, _, error = self.call(order={**self.order, "status": "refunded"}, payload=OrderCancel(reason="Retry"))
        self.assertIsNone(error)
        db.execute.assert_not_called()
        db.commit.assert_not_called()

    def test_orders_with_shipping_in_progress_cannot_be_cancelled(self):
        for changes in ({"status": "shipping_pending"}, {"status": "shipment_booked"},
                        {"status": "fulfilment_review", "shiprocket_order_id": 123}):
            with self.subTest(changes=changes):
                db, _, error = self.call(order={**self.order, **changes})
                self.assertEqual(error.status_code, 409)
                db.execute.assert_not_called()
                db.commit.assert_not_called()

    def test_review_orders_reserve_stock(self):
        self.assertIn("fulfilment_review", HOLDING_STATUSES)


class LateCaptureTests(unittest.TestCase):
    def test_cancelled_and_expired_capture_is_verified_before_recording_for_review(self):
        for status in ("cancelled", "expired"):
            with self.subTest(status=status):
                row = {"status": status, "payment_method": "prepaid", "razorpay_order_id": "order_123", "items": [],
                       "razorpay_payment_id": None, "credentials": "encrypted", "total_paise": 12500}
                db = Mock()
                db.execute.return_value.mappings.return_value.first.return_value = row
                db.execute.return_value.mappings.return_value.one.return_value = {
                    **row, "status": "fulfilment_review", "razorpay_payment_id": "pay_123"}
                with patch.object(shop_checkout.providers, "decrypt_credentials", return_value={}), \
                     patch.object(shop_checkout.providers, "captured_payment") as capture, \
                     patch.object(shop_orders_service, "post_prepaid_advance") as advance, \
                     patch.object(shop_checkout, "public_order", side_effect=lambda value: value):
                    result = shop_checkout.confirm_payment(db, "company", "order", "pay_123")
                capture.assert_called_once_with({}, "order_123", "pay_123", 12500)
                self.assertEqual(result["status"], "fulfilment_review")
                update = next(call for call in db.execute.call_args_list if "update shop_orders set" in str(call.args[0]))
                self.assertIn("'expired','cancelled'", str(update.args[0]))
                self.assertIn("expires_at<=now()", str(update.args[0]))
                self.assertIn("'fulfilment_review'", str(update.args[0]))
                self.assertIn("expires_at=null", str(update.args[0]))
                advance.assert_called_once()
                db.commit.assert_called_once()

    def test_product_locks_are_ordered_before_payment_becomes_a_hold(self):
        row = {"status": "cancelled", "payment_method": "prepaid", "razorpay_order_id": "order_123",
               "razorpay_payment_id": None, "credentials": "encrypted", "total_paise": 12500,
               "items": [{"product_id": "b"}, {"product_id": "a"}, {"product_id": "a"}]}
        db = Mock()
        db.execute.return_value.mappings.return_value.first.return_value = row
        db.execute.return_value.mappings.return_value.one.return_value = {**row, "status": "fulfilment_review"}
        with patch.object(shop_checkout.providers, "decrypt_credentials", return_value={}), \
             patch.object(shop_checkout.providers, "captured_payment"), \
             patch.object(shop_orders_service, "post_prepaid_advance"), \
             patch.object(shop_checkout, "public_order", side_effect=lambda value: value):
            shop_checkout.confirm_payment(db, "company", "order", "pay_123")
        statements = db.execute.call_args_list
        locks = [call.args[1]["id"] for call in statements if "from products" in str(call.args[0])]
        self.assertEqual(locks, ["a", "b"])
        self.assertLess(max(index for index, call in enumerate(statements) if "from products" in str(call.args[0])),
                        next(index for index, call in enumerate(statements) if "update shop_orders" in str(call.args[0])))

    def test_repeated_capture_does_not_post_another_advance_and_different_payment_is_rejected(self):
        row = {"status": "fulfilment_review", "payment_method": "prepaid", "razorpay_order_id": "order_123",
               "razorpay_payment_id": "pay_123", "credentials": "encrypted", "total_paise": 12500}
        db = Mock()
        db.execute.return_value.mappings.return_value.first.return_value = row
        with patch.object(shop_checkout.providers, "decrypt_credentials", return_value={}), \
             patch.object(shop_checkout.providers, "captured_payment"), \
             patch.object(shop_orders_service, "post_prepaid_advance") as advance, \
             patch.object(shop_checkout, "public_order", side_effect=lambda value: value):
            self.assertEqual(shop_checkout.confirm_payment(db, "company", "order", "pay_123")["status"], "fulfilment_review")
            with self.assertRaises(HTTPException) as error:
                shop_checkout.confirm_payment(db, "company", "order", "pay_other")
        self.assertEqual(error.exception.status_code, 409)
        advance.assert_not_called()
        db.commit.assert_not_called()


class FulfilmentResolutionTests(unittest.TestCase):
    def test_stock_is_locked_and_checked_before_review_is_resolved(self):
        store = uuid4()
        order = {"id": "order", "status": "fulfilment_review", "invoice_id": None, "shiprocket_order_id": None,
                 "payment_method": "prepaid", "razorpay_payment_id": "pay_123", "advance_transaction_id": "advance",
                 "items": [{"product_id": "b", "variant_id": None, "quantity": 1, "name": "B"},
                           {"product_id": "a", "variant_id": None, "quantity": 2, "name": "A"}]}
        events = []
        inventory = Mock()
        inventory._product.side_effect = lambda product, lock: events.append(("lock", product))
        inventory.available_stock.side_effect = lambda location, product, variant, exclude: (
            events.append(("check", product)) or Decimal("2"))
        db = Mock()
        with patch.object(shop_orders_service, "_order", return_value=order), \
             patch.object(shop_orders_service, "_order_out", return_value={"status": "paid"}), \
             patch.object(shop_orders_service, "stock_store", return_value={"id": store}), \
             patch("app.services.inventory_service.InventoryService", return_value=inventory):
            result = shop_orders_service.resolve_fulfilment_review(db, "company", "order",
                                                                    FulfilmentResolutionInput(ship_from_store_id=store))
        self.assertEqual(result["status"], "paid")
        self.assertEqual(events, [("lock", "a"), ("lock", "b"), ("check", "b"), ("check", "a")])
        db.commit.assert_called_once()

    def test_insufficient_stock_cannot_resolve_review(self):
        store = uuid4()
        order = {"id": "order", "status": "fulfilment_review", "invoice_id": None, "shiprocket_order_id": None,
                 "payment_method": "prepaid", "razorpay_payment_id": "pay_123", "advance_transaction_id": "advance",
                 "items": [{"product_id": "a", "variant_id": None, "quantity": 2, "name": "A"}]}
        inventory = Mock()
        inventory.available_stock.return_value = Decimal("1")
        db = Mock()
        with patch.object(shop_orders_service, "_order", return_value=order), \
             patch.object(shop_orders_service, "stock_store", return_value={"id": store}), \
             patch("app.services.inventory_service.InventoryService", return_value=inventory):
            with self.assertRaises(HTTPException) as error:
                shop_orders_service.resolve_fulfilment_review(db, "company", "order",
                                                              FulfilmentResolutionInput(ship_from_store_id=store))
        self.assertEqual(error.exception.status_code, 409)
        db.execute.assert_not_called()
        db.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
