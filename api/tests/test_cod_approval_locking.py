import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.services.shop_orders_service import approve_cod


class CodApprovalLockingTests(unittest.TestCase):
    def test_all_products_are_locked_in_order_before_availability_is_checked(self):
        events = []
        order = {"id": "order", "status": "cod_requested", "store_id": "online", "items": [
            {"product_id": "b", "variant_id": None, "quantity": 1, "name": "B"},
            {"product_id": "a", "variant_id": None, "quantity": 2, "name": "A"},
        ]}
        db = Mock()
        db.info = {}
        inventory = Mock()
        inventory._product.side_effect = lambda product, lock: events.append(("lock", product, lock))
        inventory.available_stock.side_effect = lambda store, product, variant, exclude: (
            events.append(("check", product)) or Decimal("2")
        )
        with patch("app.services.shop_orders_service._order", return_value=order), \
             patch("app.services.shop_orders_service._order_out", return_value={"status": "confirmed"}), \
             patch("app.services.shop_orders_service.get_store", return_value={"fulfilment_store_id": "warehouse"}), \
             patch("app.services.inventory_service.InventoryService", return_value=inventory):
            self.assertEqual(approve_cod(db, "company", "order")["status"], "confirmed")
        self.assertEqual(events, [("lock", "a", True), ("lock", "b", True), ("check", "b"), ("check", "a")])
        db.commit.assert_called_once()

    def test_insufficient_unreserved_stock_is_not_approved(self):
        order = {"id": "order", "status": "cod_requested", "store_id": "online", "items": [
            {"product_id": "a", "variant_id": None, "quantity": 2, "name": "A"},
        ]}
        db = Mock()
        inventory = Mock()
        inventory.available_stock.return_value = Decimal("1")
        with patch("app.services.shop_orders_service._order", return_value=order), \
             patch("app.services.shop_orders_service.get_store", return_value={"fulfilment_store_id": "warehouse"}), \
             patch("app.services.inventory_service.InventoryService", return_value=inventory):
            with self.assertRaises(HTTPException) as error:
                approve_cod(db, "company", "order")
        self.assertEqual(error.exception.status_code, 409)
        db.commit.assert_not_called()
        db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
