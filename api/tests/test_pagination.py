import unittest
import csv
from datetime import date, datetime, timezone
from io import StringIO
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes import accounts, billing, collections, deletions, inventory, purchases, settlements, shop
from app.dependencies import get_db
from app.services.pagination import cursor_page, decode_cursor
from app.services.inventory_service import InventoryService
from app.services.accounts_service import AccountsService
from app.services.settlements_service import SettlementsService
from app.services import shop_orders_service
from app.services.transaction_deletion import TransactionDeletionService
from app.services.billing_service import BillingService
from app.services.purchases_service import PurchasesService
from app.services.collections_service import CollectionsService
from app.services.refund_settlements import RefundSettlementsService
from app.services.quotation_service import QuotationService


class PaginationTests(unittest.TestCase):
    def test_inventory_products_page_filters_and_enriches_only_page_ids(self):
        class FakeResult:
            def mappings(self):
                return self

            def all(self):
                return [{"id": UUID(int=value), "home_order": 5, "name": "Same name"} for value in (1, 2, 3)]

        class FakeDb:
            def execute(self, query, params):
                self.query = str(query)
                self.params = dict(params)
                return FakeResult()

        service = object.__new__(InventoryService)
        service.db = FakeDb()
        service.company_id = "company"
        service.list_products = Mock(side_effect=lambda ids: {"items": [{"id": value} for value in ids]})
        page = service.product_page(2, search="Large BLUE", vendor_id=str(UUID(int=20)))
        self.assertEqual(service.list_products.call_args.args[0], [str(UUID(int=1)), str(UUID(int=2))])
        self.assertEqual(service.db.params["term0"], "large")
        self.assertEqual(service.db.params["term1"], "blue")
        self.assertEqual(service.db.params["limit"], 3)
        self.assertIn("v.variant_name", service.db.query)
        self.assertIn("o.vendor_id", service.db.query)
        self.assertIn("p.company_id=:company", service.db.query)
        ids = service.product_page(2, page["next_cursor"], ids_only=True)
        self.assertEqual(ids["items"], [str(UUID(int=1)), str(UUID(int=2))])
        self.assertIn("(p.home_order,p.name,p.id) >", service.db.query)
        self.assertEqual(service.db.params["id"], str(UUID(int=2)))
        self.assertEqual(service.list_products.call_count, 1)

    def test_inventory_product_paging_route_validation(self):
        app = FastAPI()
        app.include_router(inventory.router)
        service = Mock()
        service.product_page.return_value = {"items": [], "next_cursor": None}
        service.list_products.return_value = {"items": []}
        app.dependency_overrides[inventory.inventory_service] = lambda: service
        client = TestClient(app)
        self.assertEqual(client.get("/products").status_code, 200)
        service.list_products.assert_called_once()
        self.assertEqual(client.get("/products", params={"search": "blue"}).status_code, 422)
        self.assertEqual(client.get("/products", params={"page_size": 101}).status_code, 422)
        self.assertEqual(client.get("/products", params={"page_size": 10, "search": "blue", "ids_only": True}).status_code, 200)
        self.assertEqual(service.product_page.call_args.args, (10, None, "blue", None, False, True))

    def test_cursor_uses_last_returned_row_and_rejects_malformed_input(self):
        rows = [
            {"id": UUID(int=value), "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
            for value in (3, 2, 1)
        ]
        page = cursor_page(rows, 2, ("created_at", "id"))
        self.assertEqual(len(page["items"]), 2)
        boundary = decode_cursor(page["next_cursor"], ("created_at", "id"))
        self.assertEqual(boundary["id"], str(UUID(int=2)))
        self.assertIsNone(cursor_page(rows[:2], 2, ("created_at", "id"))["next_cursor"])
        for invalid in ("not-base64", page["next_cursor"] + "!", "W10"):
            with self.assertRaises(HTTPException):
                decode_cursor(invalid, ("created_at", "id"))
        invalid_reminder = cursor_page([
            {"id": UUID(int=1), "reminded_at": "not-a-timestamp"},
            {"id": UUID(int=2), "reminded_at": "not-a-timestamp"},
        ], 1, ("reminded_at", "id"))["next_cursor"]
        with self.assertRaises(HTTPException):
            decode_cursor(invalid_reminder, ("reminded_at", "id"))

    def test_stock_history_applies_store_scope_and_cursor_to_query(self):
        class FakeResult:
            def mappings(self):
                return self

            def all(self):
                return [
                    {"id": UUID(int=value), "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
                    for value in (3, 2, 1)
                ]

        class FakeDb:
            info = {}

            def execute(self, query, params):
                self.query = str(query)
                self.params = params
                return FakeResult()

        service = object.__new__(InventoryService)
        service.db = FakeDb()
        service.company_id = "company"
        service._product = lambda _: None
        store = str(UUID(int=9))
        with patch("app.services.inventory_service.allowed_stores", return_value=[store]):
            first = service.movements("product", 2)
            self.assertEqual(len(first["items"]), 2)
            self.assertEqual(service.db.params["limit"], 3)
            self.assertIn("store_id=any", service.db.query)
            self.assertEqual(service.db.params["permitted"], [store])
            service.movements("product", 2, first["next_cursor"])
            self.assertIn("(created_at,id) <", service.db.query)
            self.assertEqual(service.db.params["id"], str(UUID(int=2)))
            self.assertEqual(service.db.params["permitted"], [store])
            legacy = service.movements("product")
            self.assertNotIn("next_cursor", legacy)
            self.assertEqual(service.db.params["limit"], 50)

    def test_financial_cursors_preserve_filters_and_tie_breaker(self):
        class FakeResult:
            def mappings(self):
                return self

            def all(self):
                return [{"id": UUID(int=value), "transaction_date": date(2026, 1, 1),
                         "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
                        for value in (3, 2, 1)]

        class FakeDb:
            def execute(self, query, params):
                self.query = str(query)
                self.params = dict(params)
                return FakeResult()

        account = object.__new__(AccountsService)
        account.db = FakeDb()
        account._resolve_company_id = lambda _: "company"
        first = account.list_transactions(None, account_id="account", category="expense", page_size=2)
        account.list_transactions(None, account_id="account", category="expense", page_size=2, cursor=first["next_cursor"])
        self.assertIn("(t.transaction_date,t.created_at,t.id) <", account.db.query)
        self.assertIn("t.id desc", account.db.query)
        self.assertEqual(account.db.params["account_id"], "account")
        self.assertEqual(account.db.params["category"], "%expense%")
        self.assertEqual(account.db.params["limit"], 3)
        self.assertEqual(account.db.params["cursor_id"], str(UUID(int=2)))
        legacy = account.list_transactions(None, limit=17)
        self.assertNotIn("next_cursor", legacy)
        self.assertEqual(account.db.params["limit"], 17)
        self.assertIn("t.id limit :limit", account.db.query)

        borrowing = object.__new__(SettlementsService)
        borrowing.db = FakeDb()
        borrowing._resolve_company_id = lambda _: "company"
        borrowing._ensure_table = lambda: None
        first = borrowing.list_borrowings(None, party_id="party", page_size=2)
        borrowing.list_borrowings(None, party_id="party", page_size=2, cursor=first["next_cursor"])
        self.assertIn("(b.transaction_date,b.created_at,b.id) <", borrowing.db.query)
        self.assertIn("b.id desc", borrowing.db.query)
        self.assertEqual(borrowing.db.params["party_id"], "party")
        self.assertEqual(borrowing.db.params["cursor_id"], str(UUID(int=2)))
        legacy = borrowing.list_borrowings(None, limit=19)
        self.assertNotIn("next_cursor", legacy)
        self.assertEqual(borrowing.db.params["limit"], 19)
        self.assertNotIn("b.id desc", borrowing.db.query)

    def test_routes_validate_page_parameters_and_preserve_next_cursor(self):
        app = FastAPI()
        app.include_router(accounts.router, prefix="/accounts")
        app.include_router(inventory.router, prefix="/inventory")
        app.include_router(settlements.router, prefix="/settlements")
        app.include_router(deletions.router, prefix="/deletions")
        app.include_router(shop.admin_router, prefix="/checkout-admin")
        app.include_router(billing.router, prefix="/billing")
        app.include_router(purchases.router, prefix="/purchases")
        app.include_router(collections.router, prefix="/collections")
        app.dependency_overrides[get_db] = lambda: None
        app.dependency_overrides[shop.administrator] = lambda: {"company_id": str(UUID(int=1))}
        inventory_mock = Mock()
        inventory_mock.movements.return_value = {"items": [], "next_cursor": "next"}
        app.dependency_overrides[inventory.inventory_service] = lambda: inventory_mock
        deletion_mock = Mock()
        deletion_mock.history.return_value = {"items": [], "next_cursor": "next"}
        app.dependency_overrides[deletions.deletion_service] = lambda: deletion_mock
        client = TestClient(app)
        product = str(UUID(int=1))
        paths = ("/accounts/transactions", "/accounts/business-payments",
                 f"/inventory/products/{product}/movements", "/settlements/borrowings")
        extra_paths = ("/accounts/journal", "/deletions", "/checkout-admin/orders", "/checkout-admin/cod",
                       "/checkout-admin/enquiries", "/billing/invoices", "/billing/quotations", "/purchases", "/collections/receivables",
                       "/settlements/refunds")
        for path in paths + extra_paths:
            for query in ("page_size=0", "page_size=101", "cursor=abc", "page_size=10&cursor=" + "a" * 1001):
                with self.subTest(path=path, query=query):
                    self.assertEqual(client.get(f"{path}?{query}").status_code, 422)

        with patch.object(accounts.AccountsService, "list_transactions", return_value={"items": [], "next_cursor": "next"}), \
             patch.object(settlements.SettlementsService, "list_borrowings", return_value={"items": [], "next_cursor": "next"}):
            for path in paths:
                response = client.get(f"{path}?page_size=10")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["next_cursor"], "next")
        with patch.object(BillingService, "list_invoices", return_value={"items": [], "next_cursor": "next"}), \
                 patch.object(PurchasesService, "list_purchases", return_value={"items": [], "next_cursor": "next"}):
                for path in ("/billing/invoices", "/purchases"):
                    response = client.get(f"{path}?page_size=10")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["next_cursor"], "next")
        with patch.object(CollectionsService, "list_receivables", return_value={"items": [], "next_cursor": "next"}):
            response = client.get("/collections/receivables?page_size=10&open_only=true")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["next_cursor"], "next")
        response = client.get("/deletions?page_size=10")
        self.assertEqual(response.json()["next_cursor"], "next")
        with patch.object(accounts.AccountsService, "list_audit_journal", return_value={
            "period": "daily", "from_date": date(2026, 1, 1), "to_date": date(2026, 1, 31),
            "items": [], "buckets": [], "next_cursor": "next",
        }):
            response = client.get("/accounts/journal?page_size=10")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["next_cursor"], "next")

    def test_journal_summary_is_independent_of_page_boundary(self):
        class FakeResult:
            def __init__(self, rows):
                self.rows = rows

            def mappings(self):
                return self

            def all(self):
                return self.rows

        class FakeDb:
            def __init__(self):
                self.calls = []

            def execute(self, query, params):
                self.calls.append((str(query), dict(params)))
                if "group by 1" in str(query):
                    return FakeResult([{"period_key": "2026-01-01", "entry_count": 3,
                                        "total_inflow": 30, "total_outflow": 10, "total_transfer": 5}])
                return FakeResult([{"transaction_id": UUID(int=value), "transaction_date": date(2026, 1, 1),
                                    "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
                                   for value in (3, 2, 1)])

        service = object.__new__(AccountsService)
        service.db = FakeDb()
        service._resolve_company_id = lambda _: "company"
        first = service.list_audit_journal(None, "daily", "2026-01-01", "2026-01-31", category="sale", page_size=2)
        self.assertEqual(first["buckets"][0]["entry_count"], 3)
        self.assertEqual(first["buckets"][0]["net_flow"], 20)
        self.assertEqual(len(first["items"]), 2)
        self.assertNotIn("id", first["items"][0])
        service.list_audit_journal(None, "daily", "2026-01-01", "2026-01-31", category="sale", page_size=2, cursor=first["next_cursor"])
        aggregate, detail = service.db.calls[-2:]
        self.assertNotIn("cursor", aggregate[0])
        self.assertEqual(aggregate[1]["category"], "sale")
        self.assertIn("(t.transaction_date,t.created_at,t.id) <", detail[0])
        self.assertEqual(detail[1]["cursor_id"], str(UUID(int=2)))

    def test_checkout_histories_keep_scope_and_stable_boundaries(self):
        class FakeResult:
            def __init__(self, rows):
                self.rows = rows

            def mappings(self):
                return self

            def all(self):
                return self.rows

        class FakeDb:
            def __init__(self):
                self.calls = []

            def commit(self):
                pass

            def execute(self, query, params):
                self.calls.append((str(query), dict(params)))
                if "from shop_orders o join invoices" in str(query):
                    return FakeResult([{"outstanding": 15}])
                rows = [{"id": UUID(int=value), "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                         "transaction_date": date(2026, 1, 1)} for value in (3, 2, 1)]
                return FakeResult(rows)

        db = FakeDb()
        with patch.object(shop_orders_service, "expire_orders"), patch.object(shop_orders_service, "checkout_policy", return_value={"cod_overdue_days": 15}):
            page = shop_orders_service.staff_orders(db, "company", status="paid", shopper_id="shopper", page_size=2)
            shop_orders_service.staff_orders(db, "company", status="paid", shopper_id="shopper", page_size=2, cursor=page["next_cursor"])
            query, params = db.calls[-1]
            self.assertIn("company_id=:company", query)
            self.assertIn("shopper_id=:shopper", query)
            self.assertEqual(params["shopper"], "shopper")
            self.assertEqual(params["status"], "paid")
            self.assertEqual(params["id"], str(UUID(int=2)))
            page = shop_orders_service.list_enquiries(db, "company", "open", page_size=2)
            shop_orders_service.list_enquiries(db, "company", "open", page_size=2, cursor=page["next_cursor"])
            query, params = db.calls[-1]
            self.assertIn("e.company_id=:company", query)
            self.assertEqual(params["status"], "open")
            self.assertEqual(params["id"], str(UUID(int=2)))
            page = shop_orders_service.cod_outstanding(db, "company", page_size=2)
            self.assertEqual(page["total_outstanding"], 15)
            self.assertNotIn("transaction_date", page["settlements"][0])
            shop_orders_service.cod_outstanding(db, "company", page_size=2, cursor=page["next_cursor"])
            query, params = db.calls[-1]
            self.assertIn("company_id=:company", query)
            self.assertEqual(params["cursor_id"], str(UUID(int=2)))

    def test_deletion_history_uses_admin_and_tenant_scope(self):
        service = object.__new__(TransactionDeletionService)
        service.company_id = "company"
        service._require_admin = Mock()
        calls = []

        def all_rows(query, **params):
            calls.append((query, params))
            return [{"id": UUID(int=value), "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                     "deleted_at": datetime(2026, 1, 1, tzinfo=timezone.utc)} for value in (3, 2, 1)]

        service._all = all_rows
        first = service.history(2)
        self.assertNotIn("created_at", first["items"][0])
        service.history(2, first["next_cursor"])
        self.assertEqual(service._require_admin.call_count, 2)
        self.assertIn("company_id=:company", calls[-1][0])
        self.assertIn("(deleted_at,id) <", calls[-1][0])
        self.assertEqual(calls[-1][1]["id"], str(UUID(int=2)))

    def test_full_exports_fetch_all_pages_and_preserve_fields(self):
        service = object.__new__(AccountsService)
        calls = []

        def page(**kwargs):
            cursor = kwargs["cursor"]
            start = int(cursor or 0)
            calls.append(kwargs)
            rows = [{"transaction_date": "2026-01-01", "period_key": "2026-01-01",
                     "direction": "INFLOW", "amount": 1, "from_account_name": "A, B",
                     "to_account_name": "Bank", "reference": f"entry-{index}", "created_at": "now"}
                    for index in range(start, min(start + 100, 5101))]
            return {"items": rows, "next_cursor": str(start + 100) if start + 100 < 5101 else None}

        service.list_transactions = lambda company_id, **kwargs: page(**kwargs)
        output = service.export_full_csv("company", journal=False, category="sale")
        try:
            rows = list(csv.reader(output))
        finally:
            output.close()
        self.assertEqual(len(rows), 5102)
        self.assertEqual(rows[1][3], "A, B")
        self.assertEqual(rows[-1][6], "entry-5100")
        self.assertTrue(all(call["category"] == "sale" for call in calls))
        calls.clear()
        service.list_audit_journal = lambda company_id, period, start, end, category, source_type, **kwargs: page(**kwargs)
        output = service.export_full_csv("company", journal=True, period="daily",
                                         from_date="2026-01-01", to_date="2026-01-31")
        try:
            rows = list(csv.reader(output))
        finally:
            output.close()
        self.assertEqual(len(rows), 5102)
        self.assertEqual(rows[1][1], "2026-01-01")
        self.assertTrue(all(call["include_buckets"] is False for call in calls))

    def test_full_export_route_selects_snapshot_and_streams_csv(self):
        app = FastAPI()
        app.include_router(accounts.router, prefix="/accounts")
        db = Mock()
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        with patch.object(AccountsService, "export_full_csv", return_value=StringIO("date,amount\r\n2026-01-01,10\r\n")) as export:
            response = client.get("/accounts/transactions/export?full=true&category=sale")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "date,amount\r\n2026-01-01,10\r\n")
        db.connection.assert_called_once_with(execution_options={"isolation_level": "REPEATABLE READ"})
        self.assertEqual(export.call_args.kwargs["category"], "sale")
        self.assertFalse(export.call_args.kwargs["journal"])

    def test_invoice_and_purchase_queries_keep_store_scope_and_filters(self):
        class FakeResult:
            def __init__(self, field):
                self.field = field

            def mappings(self):
                return self

            def all(self):
                return [{"id": UUID(int=value), self.field: date(2026, 1, 1),
                         "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)} for value in (3, 2, 1)]

        class FakeDb:
            info = {"tenant_context": {"store_ids": [str(UUID(int=9))]}}

            def __init__(self, field):
                self.field = field

            def execute(self, query, params):
                self.query, self.params = str(query), dict(params)
                return FakeResult(self.field)

        for cls, method, field, filter_name, filter_value in (
            (BillingService, "list_invoices", "invoice_date", "collection_status", "UNPAID"),
            (PurchasesService, "list_purchases", "purchase_date", "payment_status", "PARTIAL"),
        ):
            service = object.__new__(cls)
            service.db = FakeDb(field)
            service._ensure_tables = lambda: None
            service._resolve_company_id = lambda _: "company"
            call = getattr(service, method)
            first = call(None, page_size=2, **{filter_name: filter_value})
            call(None, page_size=2, cursor=first["next_cursor"], **{filter_name: filter_value})
            self.assertIn("store_id = any", service.db.query)
            self.assertEqual(service.db.params["permitted"], [str(UUID(int=9))])
            self.assertEqual(service.db.params[filter_name], filter_value)
            self.assertEqual(service.db.params["cursor_id"], str(UUID(int=2)))
            self.assertIn(f".{field}", service.db.query)

    def test_receivable_cursor_keeps_due_order_and_open_filter(self):
        class FakeResult:
            def mappings(self):
                return self

            def all(self):
                return [{"id": UUID(int=value), "sort_date": date(2026, 1, 1),
                         "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)} for value in (3, 2, 1)]

        class FakeDb:
            def execute(self, query, params):
                self.query, self.params = str(query), dict(params)
                return FakeResult()

        service = object.__new__(CollectionsService)
        service.db = FakeDb()
        service._ensure_tables = lambda: None
        service._resolve_company_id = lambda _: "company"
        first = service.list_receivables(None, open_only=True, page_size=2, permitted_stores=["store"])
        self.assertNotIn("sort_date", first["items"][0])
        service.list_receivables(None, open_only=True, page_size=2, permitted_stores=["store"], cursor=first["next_cursor"])
        self.assertIn("r.status in ('UNPAID','PARTIAL')", service.db.query)
        self.assertIn("> cast(:cursor_date as date)", service.db.query)
        self.assertIn("(r.created_at,r.id) <", service.db.query)
        self.assertEqual(service.db.params["permitted"], ["store"])
        self.assertEqual(service.db.params["cursor_id"], str(UUID(int=2)))

    def test_refund_pages_keep_summary_and_status_order(self):
        class FakeResult:
            def mappings(self):
                return self

            def all(self):
                return [{"id": UUID(int=value), "status": "PENDING",
                         "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)} for value in (3, 2, 1)]

        class FakeDb:
            def execute(self, query, params):
                self.query, self.params = str(query), dict(params)
                return FakeResult()

        service = object.__new__(RefundSettlementsService)
        service.db = FakeDb()
        service.company_id = "company"
        service.summary = lambda: {"customer_count": 8}
        first = service.list("PENDING", page_size=2)
        self.assertEqual(first["summary"]["customer_count"], 8)
        self.assertEqual(len(first["items"]), 2)
        service.list("PENDING", page_size=2, cursor=first["next_cursor"])
        self.assertIn("s.status > :cursor_status", service.db.query)
        self.assertEqual(service.db.params["cursor_id"], str(UUID(int=2)))
        self.assertEqual(service.db.params["company"], "company")

    def test_quotation_cursor_retains_store_restrictions(self):
        class FakeResult:
            def mappings(self):
                return self

            def all(self):
                return [{"id": UUID(int=value), "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
                        for value in (3, 2, 1)]

        class FakeDb:
            info = {"tenant_context": {"store_ids": [str(UUID(int=9))]}}

            def execute(self, query, params):
                self.query, self.params = str(query), dict(params)
                return FakeResult()

        service = QuotationService(FakeDb())
        with patch.object(BillingService, "_resolve_company_id", return_value="company"):
            first = service.list(None, page_size=2)
            service.list(None, page_size=2, cursor=first["next_cursor"])
        self.assertIn("q.store_id=any", service.db.query)
        self.assertEqual(service.db.params["permitted"], [str(UUID(int=9))])
        self.assertEqual(service.db.params["id"], str(UUID(int=2)))


if __name__ == "__main__":
    unittest.main()
