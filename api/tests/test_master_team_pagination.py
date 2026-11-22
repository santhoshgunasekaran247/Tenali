import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import auth, inventory
from app.services.inventory_service import InventoryService
from app.services.access import check_module
from app.services.pagination import decode_cursor
from app.services.tenant_auth import TenantAuth


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class Database:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, params):
        self.query = str(query)
        self.params = dict(params)
        return Result(self.rows)


class MasterTeamPaginationTests(unittest.TestCase):
    def test_master_pages_use_scoped_search_and_stable_name_id_boundary(self):
        rows = [{"id": UUID(int=i), "name": "Same", "code": str(i), "description": None, "is_active": True} for i in (1, 2, 3)]
        service = object.__new__(InventoryService)
        service.db = Database(rows)
        service.company_id = "company-a"
        for kind, table in (("brands", "brands"), ("categories", "product_categories")):
            page = service.master_entries_page(kind, 2, search="a%_")
            self.assertEqual(len(page["items"]), 2)
            self.assertIn(f"from {table}", service.db.query)
            self.assertIn("company_id=:company", service.db.query)
            self.assertIn("strpos(lower(code),lower(:search))", service.db.query)
            self.assertEqual(service.db.params, {"company": "company-a", "search": "a%_", "limit": 3})
            service.master_entries_page(kind, 2, page["next_cursor"], "a%_")
            self.assertIn("(name,id) >", service.db.query)
            self.assertEqual(service.db.params["id"], str(UUID(int=2)))
        self.assertNotIn("next_cursor", service.master_entries("brands"))

    def test_team_pages_keep_company_search_and_tie_breaker(self):
        rows = [{"id": UUID(int=i), "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                 "email": f"{i}@example.test", "display_name": "Same", "role": "staff",
                 "is_active": True, "store_ids": None, "modules": None} for i in (1, 2, 3)]
        db = Database(rows)
        service = TenantAuth(db)
        page = service.team_page("company-a", 2, search="STAFF")
        self.assertEqual(len(page["items"]), 2)
        self.assertNotIn("created_at", page["items"][0])
        self.assertEqual(decode_cursor(page["next_cursor"], ("created_at", "id"))["id"], str(UUID(int=2)))
        self.assertIn("member.company_id=:company", db.query)
        self.assertIn("lower(account.email)", db.query)
        self.assertIn("lower(member.role)", db.query)
        self.assertEqual(db.params["company"], "company-a")
        self.assertEqual(db.params["limit"], 3)
        service.team_page("company-b", 2, page["next_cursor"], "STAFF")
        self.assertEqual(db.params["company"], "company-b")
        self.assertIn("(member.created_at,account.id) >", db.query)
        self.assertEqual(db.params["id"], str(UUID(int=2)))

    def test_inventory_route_legacy_validation_and_cursor(self):
        app = FastAPI()
        app.include_router(inventory.router)
        service = Mock()
        service.master_entries.return_value = {"items": []}
        service.master_entries_page.return_value = {"items": [], "next_cursor": None}
        app.dependency_overrides[inventory.inventory_service] = lambda: service
        client = TestClient(app)
        self.assertEqual(client.get("/lookups/brands").json(), {"items": []})
        service.master_entries.assert_called_once_with("brands")
        for params in ({"page_size": 0}, {"page_size": 101}, {"search": "x"}, {"cursor": "x"}):
            self.assertEqual(client.get("/lookups/brands", params=params).status_code, 422)
        self.assertEqual(client.get("/lookups/categories", params={"page_size": 25, "search": "x"}).json(), {"items": [], "next_cursor": None})
        service.master_entries_page.assert_called_once_with("categories", 25, None, "x")

    def test_team_route_requires_administrator_and_preserves_legacy(self):
        app = FastAPI()
        app.include_router(auth.router)
        identity = {"role": "staff", "company_id": UUID(int=1), "user_id": UUID(int=2)}
        app.dependency_overrides[auth.current_identity] = lambda: identity
        app.dependency_overrides[auth.identity_db] = lambda: object()
        client = TestClient(app)
        self.assertEqual(client.get("/team", params={"page_size": 25}).status_code, 403)
        identity["role"] = "admin"
        with patch("app.api.routes.auth.TenantAuth") as factory:
            factory.return_value.team.return_value = [{"email": "legacy"}]
            factory.return_value.team_page.return_value = {"items": [], "next_cursor": None}
            self.assertEqual(client.get("/team").json(), {"items": [{"email": "legacy"}]})
            for params in ({"page_size": 101}, {"page_size": 0}, {"cursor": "x"}, {"search": "x"}):
                self.assertEqual(client.get("/team", params=params).status_code, 422)
            self.assertEqual(client.get("/team", params={"page_size": 25, "search": "name"}).status_code, 200)
            factory.return_value.team_page.assert_called_once_with(str(UUID(int=1)), 25, None, "name")
            payload = {"role": "staff", "is_active": True}
            factory.return_value.update_member.return_value = []
            self.assertEqual(client.put(f"/team/{UUID(int=3)}", json=payload).status_code, 200)
            self.assertTrue(factory.return_value.update_member.call_args.kwargs["return_team"])
            self.assertEqual(client.put(f"/team/{UUID(int=3)}?return_team=false", json=payload).status_code, 200)
            self.assertFalse(factory.return_value.update_member.call_args.kwargs["return_team"])
            factory.return_value.add_member.return_value = []
            member = {"display_name": "User", "email": "u@example.test", "password": "long-password-123", "role": "staff"}
            self.assertEqual(client.post("/team?return_team=false", json=member).status_code, 201)
            self.assertFalse(factory.return_value.add_member.call_args.kwargs["return_team"])

    def test_update_can_skip_legacy_team_materialization(self):
        db = Mock()
        db.execute.return_value.scalar_one_or_none.return_value = "staff"
        service = TenantAuth(db)
        service.team = Mock(return_value=[{"id": "member"}])
        self.assertEqual(service.update_member("company", "member", "staff", True, return_team=False), [])
        service.team.assert_not_called()
        self.assertEqual(service.update_member("company", "member", "staff", True), [{"id": "member"}])
        service.team.assert_called_once_with("company")

    def test_invalid_cursor_rejected(self):
        service = object.__new__(InventoryService)
        service.db = Database([])
        service.company_id = "company"
        from fastapi import HTTPException
        for callback in (lambda: service.master_entries_page("brands", 25, "bad!"),
                         lambda: TenantAuth(Database([])).team_page("company", 25, "bad!")):
            with self.assertRaises(HTTPException) as error:
                callback()
            self.assertEqual(error.exception.status_code, 422)

    def test_inventory_module_permission_remains_required(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as error:
            check_module({"role": "staff", "modules": ["masters"]}, "/inventory/lookups/brands")
        self.assertEqual(error.exception.status_code, 403)
        check_module({"role": "staff", "modules": ["inventory"]}, "/inventory/lookups/categories")


if __name__ == "__main__":
    unittest.main()
