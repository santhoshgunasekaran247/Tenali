import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.dashboard import router
from app.dependencies import get_db
from app.services.dashboard_service import DashboardService


class Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one(self):
        return self.value

    def all(self):
        return self.value


class DashboardDatabase:
    def __init__(self, modules, stores=None):
        self.info = {"tenant_context": {"company_id": "company", "role": "staff", "modules": modules, "store_ids": stores}}
        self.queries = []

    def execute(self, query, params):
        sql = str(query)
        self.queries.append((sql, params.copy()))
        if "from purchases" in sql:
            return Result({"bills": 1, "total": Decimal("125.00"), "pending_receipts": 0, "quantity_to_receive": 0})
        if "from invoices where" in sql:
            return Result({"invoices": 1, "total": Decimal("100.00")})
        if "jsonb_array_elements(i.document_data" in sql:
            return Result([])
        if "from account_transactions" in sql:
            return Result({"entries": 2, "outflow": Decimal("50.00"), "inflow": Decimal("80.00")})
        raise AssertionError(f"Unexpected query: {sql}")


class DashboardPeriodTests(unittest.TestCase):
    def test_inclusive_range_and_result(self):
        db = DashboardDatabase(["billing", "purchases", "accounts"])
        summary = DashboardService(db).summary(from_date=date(2026, 1, 31), to_date=date(2026, 2, 1))
        self.assertEqual(summary["cash_flow"], {"inflow": Decimal("80.00"), "outflow": Decimal("50.00"), "net": Decimal("30.00")})
        self.assertEqual(summary["outflow"]["total"], Decimal("50.00"))
        for _, params in db.queries:
            self.assertEqual(params["start"], date(2026, 1, 31))
            self.assertEqual(params["end"], date(2026, 2, 1))
        self.assertTrue(all("<=:end" in query for query, _ in db.queries))
        for query, _ in db.queries[:3]:
            self.assertIn("cancelled_at>:end", query)
        outflow_sql = db.queries[-1][0]
        self.assertIn("from_account_id is not null and to_account_id is null", outflow_sql)

    def test_month_end_and_access_controls(self):
        db = DashboardDatabase(["billing", "accounts"], ["store"])
        summary = DashboardService(db).summary(date(2024, 2, 1))
        self.assertEqual(summary["to_date"], date(2024, 2, 29))
        self.assertIsNone(summary["outflow"])
        self.assertIsNone(summary["cash_flow"])
        self.assertEqual(len(db.queries), 2)

    def test_invalid_periods_are_rejected(self):
        service = DashboardService(DashboardDatabase([]))
        for arguments in [
            {"month": date(2026, 1, 2)},
            {"month": date(9999, 1, 1)},
            {"from_date": date(2026, 1, 1)},
            {"to_date": date(2026, 1, 1)},
            {"from_date": date(2026, 2, 1), "to_date": date(2026, 1, 1)},
            {"month": date(2026, 1, 1), "from_date": date(2026, 1, 1), "to_date": date(2026, 1, 1)},
        ]:
            with self.subTest(arguments=arguments), self.assertRaises(HTTPException) as error:
                service.summary(**arguments)
            self.assertEqual(error.exception.status_code, 422)

    def test_http_date_range_and_validation(self):
        app = FastAPI()
        app.include_router(router, prefix="/dashboard")
        db = DashboardDatabase(["billing", "purchases", "accounts"])
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        response = client.get("/dashboard", params={"from_date": "2026-01-10", "to_date": "2026-01-10"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["from_date"], "2026-01-10")
        self.assertEqual(response.json()["to_date"], "2026-01-10")
        self.assertEqual(response.json()["cash_flow"], {"inflow": 80, "outflow": 50, "net": 30})
        self.assertEqual(client.get("/dashboard", params={"from_date": "2026-01-10"}).status_code, 422)
        self.assertEqual(client.get("/dashboard", params={"from_date": "not-a-date", "to_date": "2026-01-10"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
