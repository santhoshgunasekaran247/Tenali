import unittest
from datetime import datetime, timezone
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import auth, parties
from app.dependencies import get_db
from app.services.parties_service import PartiesService


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self):
        self.company = str(UUID(int=100))
        self.calls = []
        self.contacts = [
            dict(id=UUID(int=i), company_id=UUID(int=100), party_type="customer",
                 legal_name="Same", nickname="Nick", contact_person=None, phone="123",
                 email="x@example.com", address=None, gst_number=None, is_active=True)
            for i in range(1, 4)
        ]
        self.shoppers = [
            dict(id=UUID(int=i), email=f"{i}@example.com", display_name="Same",
                 phone=None, customer_party_id=None, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
            for i in range(1, 4)
        ]

    def execute(self, query, params):
        query = str(query)
        self.calls.append((query, dict(params)))
        rows = self.shoppers if "shopper_accounts" in query else self.contacts
        if params["company_id"] != self.company:
            rows = []
        if "cursor_id" in params:
            rows = [row for row in rows if row["id"].int > UUID(params["cursor_id"]).int]
        if "search" in params:
            term = params["search"].strip("%").lower()
            fields = ("display_name", "email", "phone") if "shopper_accounts" in query else ("legal_name", "nickname", "phone")
            rows = [row for row in rows if any(term in (row.get(field) or "").lower() for field in fields)]
        return Result(rows[:params.get("limit")] if params.get("limit") is not None else rows)


class PartiesPaginationTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        app = FastAPI()
        app.include_router(parties.router, prefix="/parties")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[auth.identity_db] = lambda: self.db
        app.dependency_overrides[auth.current_identity] = lambda: {"company_id": self.db.company, "user_id": str(UUID(int=10)), "role": "admin"}
        self.app = app
        self.client = TestClient(app)

    def test_contacts_legacy_paging_search_and_cursor_validation(self):
        params = {"company_id": self.db.company}
        legacy = self.client.get("/parties", params=params)
        self.assertEqual(len(legacy.json()["items"]), 3)
        self.assertNotIn("next_cursor", legacy.json())
        first = self.client.get("/parties", params={**params, "page_size": 2, "search": " Nick "}).json()
        self.assertEqual(len(first["items"]), 2)
        second = self.client.get("/parties", params={**params, "page_size": 2, "search": "Nick", "cursor": first["next_cursor"]}).json()
        self.assertEqual([x["id"] for x in second["items"]], [str(UUID(int=3))])
        self.assertIsNone(second["next_cursor"])
        query, values = self.db.calls[-1]
        self.assertIn("(legal_name, id) >", query)
        self.assertEqual(values["limit"], 3)
        self.assertEqual(values["company_id"], self.db.company)
        self.assertEqual(self.client.get("/parties", params={**params, "page_size": 101}).status_code, 422)
        self.assertEqual(self.client.get("/parties", params={**params, "cursor": "bad"}).status_code, 422)
        self.assertEqual(self.client.get("/parties", params={**params, "page_size": 2, "cursor": "bad"}).status_code, 422)
        self.assertEqual(self.client.get("/parties", params={**params, "page_size": 2, "cursor": "a" * 1001}).status_code, 422)
        self.client.get("/parties", params={**params, "page_size": 2, "active_only": False})
        self.assertNotIn("is_active = true", self.db.calls[-1][0])
        self.client.get("/parties", params={"company_id": str(UUID(int=999)), "page_size": 2})
        self.assertEqual(self.db.calls[-1][1]["company_id"], str(UUID(int=999)))

    def test_existing_limited_service_call_keeps_legacy_response(self):
        result = PartiesService(self.db).list(self.db.company, limit=2)
        self.assertEqual(len(result["items"]), 2)
        self.assertNotIn("next_cursor", result)
        self.assertEqual(self.db.calls[-1][1]["limit"], 2)

    def test_online_paging_search_scope_and_authorization(self):
        legacy = self.client.get("/parties/online-customers")
        self.assertEqual(len(legacy.json()["items"]), 3)
        self.assertNotIn("next_cursor", legacy.json())
        self.assertNotIn("created_at", legacy.json()["items"][0])
        first = self.client.get("/parties/online-customers", params={"page_size": 2, "search": "example.com"}).json()
        second = self.client.get("/parties/online-customers", params={"page_size": 2, "search": "example.com", "cursor": first["next_cursor"]}).json()
        self.assertEqual([x["id"] for x in second["items"]], [str(UUID(int=3))])
        self.assertIsNone(second["next_cursor"])
        query, params = self.db.calls[-1]
        self.assertIn("id > cast(:cursor_id as uuid)", query)
        self.assertIn("strpos(lower", query)
        self.assertEqual(params["company_id"], self.db.company)
        self.assertEqual(params["limit"], 3)
        self.assertEqual(self.client.get("/parties/online-customers", params={"page_size": 0}).status_code, 422)
        self.assertEqual(self.client.get("/parties/online-customers", params={"page_size": 2, "cursor": "bad"}).status_code, 422)
        self.assertEqual(self.client.get("/parties/online-customers", params={"page_size": 2, "search": "x" * 301}).status_code, 422)
        self.app.dependency_overrides[auth.current_identity] = lambda: {"company_id": self.db.company, "role": "staff"}
        self.assertEqual(self.client.get("/parties/online-customers", params={"page_size": 2}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
