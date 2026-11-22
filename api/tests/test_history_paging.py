import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes import purchases, settlements
from app.dependencies import get_db
from app.services.purchases_service import PurchasesService
from app.services.refund_settlements import RefundSettlementsService
from app.services.settlements_service import SettlementsService
from app.services import shop_orders_service


class Result:
    def __init__(self, exists=False):
        self.exists = exists

    def scalar_one_or_none(self):
        return UUID(int=1) if self.exists else None

    def mappings(self):
        return self

    def all(self):
        return [{"id": UUID(int=value), "payment_date": date(2026, 1, 1),
                 "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
                for value in (3, 2, 1)]


class FakeDb:
    info = {}

    def __init__(self):
        self.calls = []

    def execute(self, query, params):
        self.calls.append((str(query), dict(params)))
        return Result("select id\n                from purchases" in str(query))


class HistoryPagingTests(unittest.TestCase):
    def test_purchase_payment_pages_use_scope_and_stable_boundary(self):
        service = object.__new__(PurchasesService)
        service.db = FakeDb()
        service._ensure_tables = lambda: None
        service._resolve_company_id = lambda _: "company"
        store = str(UUID(int=4))
        with patch("app.services.purchases_service.allowed_stores", return_value=[store]):
            first = service.list_purchase_payments("purchase", None, page_size=2)
            self.assertEqual(len(first["items"]), 2)
            self.assertEqual(service.db.calls[0][1]["permitted"], [store])
            self.assertIn("store_id=any", service.db.calls[0][0])
            service.list_purchase_payments("purchase", None, page_size=2, cursor=first["next_cursor"])
            sql, params = service.db.calls[-1]
            self.assertIn("(payment_date,created_at,id) <", sql)
            self.assertEqual(params["cursor_id"], str(UUID(int=2)))
            self.assertEqual(params["limit"], 3)

    def test_purchase_export_uses_filters_and_accessible_stores(self):
        service = object.__new__(PurchasesService)
        service.db = FakeDb()
        service._ensure_tables = lambda: None
        service._resolve_company_id = lambda _: "company"
        store = str(UUID(int=4))
        with patch.object(Result, "all", return_value=[]), patch("app.services.purchases_service.allowed_stores", return_value=[store]):
            service.export_purchase_register_csv(None, all_dates=True, payment_status="unpaid", store_id=store)
        sql, params = service.db.calls[-1]
        self.assertIn("p.store_id = any", sql)
        self.assertEqual((params["from_date"], params["to_date"]), (None, None))
        self.assertEqual((params["payment_status"], params["store_id"], params["permitted"]), ("UNPAID", store, [store]))

    def test_borrowing_range_applies_before_cursor(self):
        service = object.__new__(SettlementsService)
        service.db = FakeDb()
        service._ensure_table = lambda: None
        service._resolve_company_id = lambda _: "company"
        first = date(2026, 1, 1)
        last = date(2026, 1, 31)
        service.list_borrowings(None, from_date=first, to_date=last)
        sql, params = service.db.calls[-1]
        self.assertIn("b.transaction_date >= :from_date", sql)
        self.assertEqual((params["from_date"], params["to_date"]), (first, last))
        with self.assertRaises(HTTPException):
            service.list_borrowings(None, from_date=last, to_date=first)

    def test_invalid_ranges_and_cursor_are_rejected_at_routes(self):
        app = FastAPI()
        app.include_router(purchases.router, prefix="/purchases")
        app.include_router(settlements.router, prefix="/settlements")
        app.dependency_overrides[get_db] = lambda: None
        client = TestClient(app)
        for path in ("/purchases", "/settlements/borrowings", "/settlements/refunds"):
            self.assertEqual(client.get(path, params={"from_date": "2026-02-01", "to_date": "2026-01-01"}).status_code, 422)
        self.assertEqual(client.get("/purchases/abc/payments", params={"cursor": "abc"}).status_code, 422)

    def test_orders_date_range_is_in_india_time_before_cursor(self):
        db = FakeDb()
        db.commit = lambda: None
        with patch("app.services.shop_orders_service.expire_orders"):
            shop_orders_service.staff_orders(db, "company", page_size=2,
                                             from_date=date(2026, 1, 1), to_date=date(2026, 1, 31))
        sql, params = db.calls[-1]
        self.assertIn("at time zone 'Asia/Kolkata'", sql)
        self.assertIn("created_at <", sql)
        self.assertEqual(params["to_date"], date(2026, 1, 31))

    def test_refund_range_uses_india_calendar_and_keeps_summary_independent(self):
        service = object.__new__(RefundSettlementsService)
        service.db = FakeDb()
        service.company_id = "company"
        first, last = date(2026, 1, 1), date(2026, 1, 31)
        service.list("PENDING", from_date=first, to_date=last, include_summary=False)
        sql, params = service.db.calls[-1]
        self.assertIn("s.created_at <", sql)
        self.assertIn("at time zone 'Asia/Kolkata'", sql)
        self.assertEqual((params["from_date"], params["to_date"]), (first, last))
        with self.assertRaises(HTTPException):
            service.list("PENDING", from_date=last, to_date=first)


if __name__ == "__main__":
    unittest.main()
