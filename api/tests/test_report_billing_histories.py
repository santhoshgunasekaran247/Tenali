import csv
import unittest
from datetime import date, datetime, timezone
from io import StringIO
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import billing, reports
from app.dependencies import get_db
from app.services.billing_service import BillingService
from app.services.pagination import decode_cursor
from app.services.access import check_module
from app.services.quotation_service import QuotationService
from fastapi import HTTPException


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class FakeDb:
    info = {}

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, query, params):
        self.calls.append((str(query), dict(params)))
        return Result(self.rows)


class HistoryTests(unittest.TestCase):
    def test_audit_cursor_filters_company_and_preserves_legacy_offset(self):
        rows = [{"id": UUID(int=i), "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                 "action": "change", "entity_type": "invoice", "entity_id": str(i),
                 "old_value": None, "new_value": None, "user_id": None, "actor_user_id": None}
                for i in (3, 2, 1)]
        db = FakeDb(rows)
        app = FastAPI()
        app.include_router(reports.router)
        app.dependency_overrides[get_db] = lambda: db
        with patch("app.api.routes.reports.CompanyService") as company:
            company.return_value.get.return_value = {"id": UUID(int=9)}
            client = TestClient(app)
            first = client.get("/audit-events", params={"page_size": 2, "from_date": "2026-01-01", "to_date": "2026-01-31"}).json()
            self.assertEqual(len(first["items"]), 2)
            self.assertEqual(decode_cursor(first["next_cursor"], ("created_at", "id"))["id"], str(UUID(int=2)))
            response = client.get("/audit-events", params={"page_size": 2, "cursor": first["next_cursor"], "from_date": "2026-01-01"})
            self.assertEqual(response.status_code, 200)
            query, params = db.calls[-1]
            self.assertIn("(created_at,id) <", query)
            self.assertIn("at time zone 'Asia/Kolkata'", query)
            self.assertEqual(params["company"], str(UUID(int=9)))
            self.assertEqual(params["id"], str(UUID(int=2)))
            self.assertEqual(params["limit"], 3)
            self.assertEqual(client.get("/audit-events", params={"cursor": "invalid", "page_size": 2}).status_code, 422)
            self.assertEqual(client.get("/audit-events", params={"cursor": "x"}).status_code, 422)
            self.assertEqual(client.get("/audit-events", params={"page_size": 10, "from_date": "2026-02-01", "to_date": "2026-01-01"}).status_code, 422)
            legacy = client.get("/audit-events", params={"offset": 4, "limit": 10}).json()
            self.assertNotIn("next_cursor", legacy)
            self.assertEqual(db.calls[-1][1]["offset"], 4)
            self.assertIn("offset :offset", db.calls[-1][0])

    def test_reconcile_csv_is_complete_and_company_scoped(self):
        db = FakeDb([{"created_at": f"2026-01-{i % 28 + 1:02d}", "healed_count": i, "triggered_by": 'a,"b"'}
                     for i in range(151)])
        service = object.__new__(BillingService)
        service.db = db
        service._ensure_tables = lambda: None
        service._resolve_company_id = lambda company: "authorized-company"
        rows = list(csv.reader(StringIO(service.export_reconcile_runs_csv(None))))
        self.assertEqual(len(rows), 152)
        self.assertEqual(rows[1][2], 'a,"b"')
        query, params = db.calls[-1]
        self.assertNotIn("limit", query.lower())
        self.assertEqual(params["company_id"], "authorized-company")
        self.assertIn("created_at desc, id desc", query)

    def test_billing_routes_validate_and_forward_date_ranges(self):
        app = FastAPI()
        app.include_router(billing.router)
        app.dependency_overrides[get_db] = lambda: FakeDb([])
        with patch("app.api.routes.billing.BillingService") as invoices, patch("app.api.routes.billing.QuotationService") as quotations:
            invoices.return_value.list_invoices.return_value = {"items": [], "next_cursor": None}
            quotations.return_value.list.return_value = {"items": [], "next_cursor": None}
            client = TestClient(app)
            for path in ("/invoices", "/quotations"):
                self.assertEqual(client.get(path, params={"from_date": "2026-02-01", "to_date": "2026-01-01"}).status_code, 422)
                self.assertEqual(client.get(path, params={"page_size": 10, "from_date": "2026-01-01", "to_date": "2026-01-31"}).status_code, 200)
            self.assertEqual(str(invoices.return_value.list_invoices.call_args.kwargs["from_date"]), "2026-01-01")
            self.assertEqual(str(quotations.return_value.list.call_args.kwargs["to_date"]), "2026-01-31")

    def test_history_queries_apply_date_and_store_scopes(self):
        db = FakeDb([])
        with patch("app.services.quotation_service.BillingService") as billing_service, \
             patch("app.services.quotation_service.allowed_stores", return_value=["permitted"]):
            billing_service.return_value._resolve_company_id.return_value = "company"
            QuotationService(db).list(None, page_size=10, from_date=date(2026, 1, 1), to_date=date(2026, 1, 31))
        query, params = db.calls[-1]
        self.assertIn("q.quotation_date>=", query)
        self.assertIn("q.quotation_date<=", query)
        self.assertEqual(params["permitted"], ["permitted"])
        self.assertEqual(params["from_date"], date(2026, 1, 1))

    def test_export_and_audit_paths_require_their_modules(self):
        identity = {"role": "viewer", "modules": ["inventory"]}
        for path in ("/billing/invoices/reconcile-runs/export", "/reports/audit-events"):
            with self.subTest(path=path), self.assertRaises(HTTPException) as error:
                check_module(identity, path)
            self.assertEqual(error.exception.status_code, 403)

    def test_sales_register_keeps_legacy_dates_and_restricts_store_scope(self):
        class SalesResult(Result):
            def scalar_one_or_none(self):
                return "29GST"

        class SalesDb(FakeDb):
            def execute(self, query, params):
                self.calls.append((str(query), dict(params)))
                return SalesResult([])

        db = SalesDb([])
        service = object.__new__(BillingService)
        service.db = db
        service._ensure_tables = lambda: None
        service._resolve_company_id = lambda company: "company"
        with patch("app.services.billing_service.allowed_stores", return_value=["permitted-store"]):
            service.export_sales_register_csv(None)
            query, params = db.calls[-1]
            self.assertEqual(params["from_date"], date.today().replace(day=1))
            self.assertEqual(params["to_date"], date.today())
            self.assertEqual(params["permitted"], ["permitted-store"])
            self.assertIn("i.store_id = any", query)
            service.export_sales_register_csv(None, "2026-03-01", "2026-03-31",
                                              store_id="selected-store", collection_status="partial", all_time=True)
            query, params = db.calls[-1]
            self.assertEqual(params["from_date"], date(2026, 3, 1))
            self.assertEqual(params["to_date"], date(2026, 3, 31))
            self.assertEqual(params["store_id"], "selected-store")
            self.assertEqual(params["collection_status"], "PARTIAL")
            self.assertIn("i.collection_status = :collection_status", query)
            self.assertIn("i.store_id = cast(:store_id as uuid)", query)
            self.assertEqual(params["permitted"], ["permitted-store"])
            service.export_sales_register_csv(None, all_time=True)
            self.assertIsNone(db.calls[-1][1]["from_date"])
            self.assertIsNone(db.calls[-1][1]["to_date"])
            with self.assertRaises(HTTPException):
                service.export_sales_register_csv(None, collection_status="wrong")

    def test_sales_register_route_forwards_optional_filters(self):
        app = FastAPI()
        app.include_router(billing.router)
        app.dependency_overrides[get_db] = lambda: FakeDb([])
        with patch("app.api.routes.billing.BillingService") as service:
            service.return_value.export_sales_register_csv.return_value = "header\r\n"
            store = str(UUID(int=20))
            result = TestClient(app).get("/invoices/reports/sales-register/export", params={
                "all_time": "true", "store_id": store, "collection_status": "PARTIAL"})
            self.assertEqual(result.status_code, 200)
            kwargs = service.return_value.export_sales_register_csv.call_args.kwargs
            self.assertEqual(kwargs["store_id"], store)
            self.assertEqual(kwargs["collection_status"], "PARTIAL")
            self.assertTrue(kwargs["all_time"])


if __name__ == "__main__":
    unittest.main()
