import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes import collections
from app.dependencies import get_db
from app.services.collections_service import CollectionsService
from app.services.pagination import decode_cursor
from tests import test_finance_integrity as finance


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return UUID(int=9)


class Database:
    def __init__(self, rows):
        self.rows = rows
        self.info = {"tenant_context": {"role": "staff", "store_ids": [str(UUID(int=10))]}}
        self.calls = []

    def execute(self, query, params):
        self.calls.append((str(query), dict(params)))
        return Result(self.rows)


class ReceivablesPagingTests(unittest.TestCase):
    def service(self, rows):
        service = CollectionsService(Database(rows))
        service._ensure_tables = lambda: None
        service._resolve_company_id = lambda _: "company"
        return service

    def test_due_reminders_bound_page_scope_and_stable_ties(self):
        rows = [{"id": UUID(int=n), "sort_date": date(2026, 1, 1),
                 "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)} for n in (1, 2, 3)]
        service = self.service(rows)
        page = service.list_due_reminders(None, as_of=date(2026, 2, 1), store_id="store", page_size=2)
        self.assertEqual(len(page["items"]), 2)
        self.assertNotIn("sort_date", page["items"][0])
        self.assertEqual(decode_cursor(page["next_cursor"], ("sort_date", "created_at", "id"))["id"], str(UUID(int=2)))
        service.list_due_reminders(None, as_of=date(2026, 2, 1), store_id="store", page_size=2, cursor=page["next_cursor"])
        query, params = service.db.calls[-1]
        self.assertIn("(coalesce(r.reminder_date,r.due_date),r.created_at,r.id) >", query)
        self.assertIn("r.id asc", query)
        self.assertIn("r.company_id = :company_id", query)
        self.assertIn("r.status in ('UNPAID','PARTIAL')", query)
        self.assertEqual(params["limit"], 3)
        self.assertEqual(params["as_of"], date(2026, 2, 1))
        self.assertEqual(params["store"], "store")
        self.assertEqual(params["permitted"], [str(UUID(int=10))])
        service.db.rows = rows[:2]
        self.assertIsNone(service.list_due_reminders(None, page_size=2)["next_cursor"])
        self.assertNotIn("next_cursor", service.list_due_reminders(None))

    def test_history_pages_preserve_filters_scope_and_tie_breaker(self):
        rows = [{"id": UUID(int=n), "reminded_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
                for n in (3, 2, 1)]
        service = self.service(rows)
        filters = dict(from_date=date(2025, 1, 1), to_date=date(2026, 2, 1), reminded_by=" ops ", store_id="store", page_size=2)
        page = service.list_reminder_history("receivable", None, **filters)
        service.list_reminder_history("receivable", None, cursor=page["next_cursor"], **filters)
        scope_query, scope = service.db.calls[-2]
        query, params = service.db.calls[-1]
        self.assertIn("i.store_id = any", scope_query)
        self.assertEqual(scope["permitted"], [str(UUID(int=10))])
        self.assertEqual(scope["store"], "store")
        self.assertIn("(reminded_at,id) <", query)
        self.assertIn("order by reminded_at desc,id desc", query)
        self.assertEqual(params["cursor_id"], str(UUID(int=2)))
        self.assertEqual(params["reminded_by"], "%ops%")
        self.assertEqual(params["from_date"], filters["from_date"])
        self.assertEqual(params["to_date"], filters["to_date"])
        self.assertEqual(params["receivable_id"], "receivable")
        self.assertEqual(params["company_id"], "company")
        self.assertEqual(params["limit"], 3)
        with self.assertRaises(HTTPException):
            service.list_reminder_history("receivable", None, from_date=date(2026, 2, 1), to_date=date(2026, 1, 1))

    def test_open_ledger_has_no_implicit_age_filter_and_applies_store_scope(self):
        service = self.service([])
        service.list_receivables(None, open_only=True, page_size=25)
        query, params = service.db.calls[-1]
        self.assertIn("r.status in ('UNPAID','PARTIAL')", query)
        self.assertIsNone(params["from_date"])
        self.assertIsNone(params["to_date"])
        self.assertEqual(params["permitted"], [str(UUID(int=10))])
        service.list_receivables(None, status="SETTLED", page_size=25)
        self.assertEqual(service.db.calls[-1][1]["status"], "SETTLED")

    def test_invalid_cursors_and_empty_store_scope_are_not_ignored(self):
        service = self.service([])
        for call in (
            lambda: service.list_due_reminders(None, page_size=10, cursor="not-a-cursor"),
            lambda: service.list_reminder_history("receivable", None, page_size=10, cursor="not-a-cursor"),
        ):
            with self.assertRaises(HTTPException) as error:
                call()
            self.assertEqual(error.exception.status_code, 422)
        service.db.info["tenant_context"]["store_ids"] = []
        service.list_due_reminders(None, page_size=10)
        self.assertEqual(service.db.calls[-1][1]["permitted"], [])
        service.list_receivables(None, permitted_stores=[str(UUID(int=10))], page_size=10)
        self.assertEqual(service.db.calls[-1][1]["permitted"], [])

    def test_search_and_exact_deep_link_filters_are_bounded_and_scoped(self):
        service = self.service([])
        service.list_receivables(None, search="older invoice", open_only=True, page_size=25)
        query, params = service.db.calls[-1]
        self.assertIn("strpos(lower(p.legal_name)", query)
        self.assertEqual(params["search"], "older invoice")
        self.assertEqual(params["limit"], 26)
        self.assertIsNone(params["from_date"])
        for key, expected in (("invoice_id", "r.invoice_id"), ("receivable_id", "r.id")):
            if key == "invoice_id":
                service.list_receivables(None, page_size=1, invoice_id=str(UUID(int=100)))
            else:
                service.list_receivables(None, page_size=1, receivable_id=str(UUID(int=100)))
            query, params = service.db.calls[-1]
            self.assertIn(f"{expected} = cast(:{key} as uuid)", query)
            self.assertEqual(params[key], str(UUID(int=100)))
            self.assertEqual(params["limit"], 2)
            self.assertEqual(params["permitted"], [str(UUID(int=10))])

    def test_reminder_routes_validate_and_keep_legacy_calls(self):
        app = FastAPI()
        app.include_router(collections.router)
        app.dependency_overrides[get_db] = lambda: Mock()
        service = Mock()
        service.list_due_reminders.return_value = {"items": [], "next_cursor": "next"}
        service.list_reminder_history.return_value = {"items": [], "next_cursor": "history"}
        service.list_receivables.return_value = {"items": []}
        with patch.object(collections, "CollectionsService", return_value=service):
            client = TestClient(app)
            for path in ("/receivables-reminders", "/receivables/id/reminders"):
                self.assertEqual(client.get(path).status_code, 200)
                for params in ({"cursor": "x"}, {"page_size": 0}, {"page_size": 101}, {"page_size": 25, "cursor": "x" * 1001}):
                    self.assertEqual(client.get(path, params=params).status_code, 422)
            response = client.get("/receivables/id/reminders", params={"page_size": 10, "cursor": "abc", "reminded_by": "ops", "from_date": "2026-01-01", "store_id": "store"})
            self.assertEqual(response.json()["next_cursor"], "history")
            self.assertEqual(service.list_reminder_history.call_args.kwargs["page_size"], 10)
            self.assertEqual(service.list_reminder_history.call_args.kwargs["cursor"], "abc")
            self.assertEqual(service.list_reminder_history.call_args.kwargs["store_id"], "store")
            identifier = str(UUID(int=100))
            response = client.get("/receivables", params={"page_size": 1, "invoice_id": identifier, "search": "old"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(service.list_receivables.call_args.kwargs["invoice_id"], identifier)
            self.assertEqual(service.list_receivables.call_args.kwargs["search"], "old")
            self.assertEqual(client.get("/receivables", params={"invoice_id": "invalid"}).status_code, 422)


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only paging tests")
class ReceivablesPagingDatabaseTests(unittest.TestCase):
    setUp = finance.FinanceIntegrityTests.setUp
    tearDown = finance.FinanceIntegrityTests.tearDown

    def test_due_and_history_walk_ties_without_duplicates_and_enforce_scope(self):
        from app.schemas.collections import ReceivableCreate

        ids = []
        for reference in ("old-open-1", "old-open-2", "old-open-3"):
            created = self.collections.create_receivable(self.company, ReceivableCreate(
                party_id=self.party, reference=reference, amount_due=100, due_date=date(2020, 1, 1)))
            ids.append(str(created["id"]))
        self.db.execute(self.text("""
            update receivables set created_at='2020-01-01T00:00:00Z'
            where company_id=:company
        """), {"company": self.company})
        collected, cursor = [], None
        for _ in range(3):
            page = self.collections.list_due_reminders(self.company, as_of=date(2026, 1, 1), page_size=2, cursor=cursor)
            collected.extend(str(item["id"]) for item in page["items"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(collected, sorted(ids))
        self.assertEqual(len(self.collections.list_receivables(self.company, open_only=True)["items"]), 3)
        beyond_first = self.collections.list_receivables(self.company, open_only=True, page_size=1)["items"][0]["id"]
        target = next(identifier for identifier in ids if identifier != str(beyond_first))
        resolved = self.collections.list_receivables(self.company, receivable_id=target, page_size=1)
        self.assertEqual(str(resolved["items"][0]["id"]), target)
        searched = self.collections.list_receivables(self.company, search="old-open-3", open_only=True, page_size=1)
        self.assertEqual(searched["items"][0]["reference"], "old-open-3")

        log_ids = sorted(str(uuid4()) for _ in range(3))
        for identifier in log_ids:
            self.db.execute(self.text("""
                insert into receivable_reminders(id,receivable_id,company_id,reminded_at,reminded_by)
                values(:id,:receivable,:company,'2026-01-01T00:00:00Z','ops')
            """), {"id": identifier, "receivable": ids[0], "company": self.company})
        first = self.collections.list_reminder_history(ids[0], self.company, reminded_by="ops", page_size=2)
        second = self.collections.list_reminder_history(ids[0], self.company, reminded_by="ops", page_size=2, cursor=first["next_cursor"])
        self.assertEqual([str(item["id"]) for item in first["items"] + second["items"]], list(reversed(log_ids)))
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(self.collections.list_due_reminders(self.company, as_of=date(2019, 1, 1), page_size=2)["items"], [])
        self.db.info["tenant_context"] = {"role": "staff", "store_ids": [self.store_id]}
        self.assertEqual(self.collections.list_due_reminders(self.company, page_size=2)["items"], [])
        self.assertEqual(self.collections.list_receivables(self.company, open_only=True, page_size=2)["items"], [])
        with self.assertRaises(HTTPException) as error:
            self.collections.list_reminder_history(ids[0], self.company, page_size=2)
        self.assertEqual(error.exception.status_code, 404)

    def test_invoice_resolution_finds_record_beyond_first_page(self):
        from app.schemas.collections import ReceivableCreate
        self.collections.create_receivable(self.company, ReceivableCreate(
            party_id=self.party, amount_due=100, due_date=date(2020, 1, 1)))
        invoice = finance.FinanceIntegrityTests.invoice(self, initial=0)
        linked = self.collections.list_receivables(self.company, invoice_id=str(invoice["id"]), page_size=1)
        self.assertEqual(str(linked["items"][0]["invoice_id"]), str(invoice["id"]))
        first_page = self.collections.list_receivables(self.company, open_only=True, page_size=1)
        self.assertNotEqual(str(first_page["items"][0]["id"]), str(linked["items"][0]["id"]))
