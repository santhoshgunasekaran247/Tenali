import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import HTTPException

from app.api.routes import shop


class PaymentCompletionTests(unittest.TestCase):
    def test_status_is_scoped_to_workspace_and_shopper_without_provider_requests(self):
        company, shopper, order = uuid4(), uuid4(), uuid4()
        db = MagicMock()
        db.execute.return_value.mappings.return_value.first.return_value = {
            "id": order, "status": "paid", "razorpay_payment_id": "pay_fixture"}
        result = shop.order_status(order, {"id": company}, {"id": shopper}, db)
        self.assertEqual(result["status"], "paid")
        query, parameters = db.execute.call_args.args
        self.assertEqual(parameters, {"company": company, "shopper": shopper, "id": order})
        for condition in ("company_id=:company", "shopper_id=:shopper", "id=:id"):
            self.assertIn(condition, str(query))
        columns = str(query).split("from shop_orders")[0]
        self.assertNotIn("credentials", columns)
        db.commit.assert_not_called()
        db.execute.assert_called_once()

    def test_missing_or_unowned_order_returns_not_found(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.first.return_value = None
        with self.assertRaises(HTTPException) as raised:
            shop.order_status(uuid4(), {"id": uuid4()}, {"id": uuid4()}, db)
        self.assertEqual(raised.exception.status_code, 404)
