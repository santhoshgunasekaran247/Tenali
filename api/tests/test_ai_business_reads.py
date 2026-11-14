import json
import os
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.ai.business_reads import business_lookup
from app.ai.capabilities import REGISTRY, available_capabilities, current_identity, execute_lookup
from app.ai.schemas import AssistantOutput, BusinessLookupArguments, ConversationCreate, MessageCreate, ReadLookup
from app.ai.provider import OpenAIProvider, ProviderResult
from app.ai.service import AssistantService
from app.services.accounts_service import AccountsService
from app.services.billing_service import BillingService
from app.services.collections_service import CollectionsService
from app.services.purchases_service import PurchasesService
from schema_support import apply_ai_business_read_migration
from test_tenancy import TenantDatabaseCase
import test_ai_reads as read_fixtures


def lookup(key, **overrides):
    args = dict(query="", store_id=None, limit=2, from_date=None, to_date=None, as_of=None, status=None)
    args.update(overrides)
    return ReadLookup(capability=key, arguments=BusinessLookupArguments(**args))


class BusinessReadUnitTests(unittest.TestCase):
    def test_typed_filters_reject_injection_invalid_dates_and_unsupported_filters(self):
        self.assertEqual(lookup("accounts", as_of=date(2026, 11, 1)).arguments.as_of, date(2026, 11, 1))
        for key, filters in (
            ("accounts", {"store_id": uuid4()}), ("reorder", {"from_date": date.today()}),
            ("invoices", {"as_of": date.today()}), ("period_locks", {"status": "PENDING"}),
            ("refunds", {"status": ""}), ("refunds", {"status": "UNPAID"}),
            ("purchases", {"from_date": date(2026, 11, 2), "to_date": date(2026, 11, 1)}),
            ("transactions", {"query": "a"}),
        ):
            with self.assertRaises(ValidationError):
                lookup(key, **filters)
        args = lookup("invoices").arguments.model_dump(mode="json")
        with self.assertRaises(ValidationError):
            ReadLookup.model_validate({"capability": "invoices", "arguments": {**args, "company_id": str(uuid4())}})
        with self.assertRaises(ValidationError):
            ReadLookup.model_validate({"capability": "invoices", "arguments": {**args, "from_date": "not-date"}})
        with self.assertRaises(ValidationError):
            ReadLookup.model_validate({"capability": "products", "arguments": {**args, "from_date": "2026-11-01"}})
        # An unnamed stock question in the shared shape is the per-store balance listing.
        self.assertEqual(ReadLookup.model_validate({"capability": "products", "arguments": args}).capability, "reconciliation")
        narrowed = ReadLookup.model_validate({"capability": "products", "arguments": {**args, "query": "copper"}})
        self.assertEqual(narrowed.arguments.model_dump(), {"query": "copper", "store_id": None, "limit": args["limit"]})
        # Observed reply: catalogue-shaped variants args mean "no date/status filters".
        variants = ReadLookup.model_validate({"capability": "variants", "arguments": {"query": "copper bottle", "store_id": None, "limit": 5}})
        self.assertIsNone(variants.arguments.status)

    def test_company_ledgers_are_hidden_and_rejected_for_store_limited_members(self):
        items = [{"key": key, "enabled": True, "compatible": True, "tenant_allowed": True,
                  "version": 1, "tenant_version": 1, "description": key} for key in REGISTRY]
        for stores in ([], [str(uuid4())]):
            identity = {"company_id": uuid4(), "role": "staff", "modules": None, "store_ids": stores}
            with patch("app.ai.capabilities.platform_capabilities", return_value={"items": items}):
                visible = {item["key"] for item in available_capabilities(Mock(), identity)}
            self.assertTrue({"accounts", "transactions", "borrowings"}.isdisjoint(visible))
            self.assertIn("invoices", visible)
            for key in ("accounts", "transactions", "borrowings"):
                with self.assertRaises(HTTPException) as error:
                    business_lookup(Mock(), identity, key, lookup(key).arguments)
                self.assertEqual(error.exception.status_code, 403)

    def test_unmigrated_database_cannot_run_runtime_ddl(self):
        with patch("app.ai.business_reads.managed_schema", return_value=False), \
             patch("app.ai.business_reads.BillingService") as service:
            with self.assertRaises(HTTPException) as error:
                business_lookup(Mock(), {"company_id": uuid4(), "role": "owner"}, "invoices", lookup("invoices").arguments)
            self.assertEqual(error.exception.status_code, 503)
            service.assert_not_called()

    def test_financial_projection_excludes_full_documents_contacts_and_totals(self):
        identity = {"company_id": uuid4(), "role": "owner"}
        with patch("app.ai.capabilities.business_lookup", return_value={"items": [
            {"id": "one", "invoice_number": "INV", "total": Decimal("15.25"),
             "document_data": "private payload", "customer_gst": "private", "notes": "private"},
            {"id": "two"}], "note": "Current state"}) as service:
            result = execute_lookup(Mock(), identity, lookup("invoices", limit=1))
        self.assertTrue(result["more_matches"])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["total"], Decimal("15.25"))
        self.assertNotIn("document_data", result["items"][0])
        self.assertNotIn("customer_gst", result["items"][0])
        self.assertNotIn("private", json.dumps(result, default=str))
        self.assertEqual(service.call_args.args[3].limit, 1)
        with self.assertRaises(HTTPException) as error:
            execute_lookup(Mock(), {**identity, "role": "staff", "modules": ["inventory"]}, lookup("invoices"))
        self.assertEqual(error.exception.status_code, 403)

    def test_old_catalogue_contract_fingerprints_are_unchanged(self):
        from app.ai.schemas import LookupArguments
        import hashlib
        adapter = REGISTRY["products"]
        contract = {"key": adapter.key, "path": adapter.module_path, "safety": "read",
                    "adapter_version": adapter.adapter_version, "fields": adapter.fields,
                    "input": LookupArguments.model_json_schema()}
        self.assertEqual(adapter.fingerprint, hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest())

    def test_provider_validates_business_proposals_and_charges_invalid_filter_responses(self):
        proposal = lookup("invoices", status="PARTIAL").model_dump(mode="json")
        output = {"reply": "Checking matching invoices.", "clarification": None, "lookups": [proposal]}
        response = SimpleNamespace(status="completed", id="mock-business", output_text=json.dumps(output),
            usage=SimpleNamespace(input_tokens=100, output_tokens=30, input_tokens_details=SimpleNamespace(cached_tokens=0)))
        with patch("app.ai.provider.OpenAI") as client:
            create = client.return_value.__enter__.return_value.responses.create
            create.return_value = response
            config = {"routine_model": "fixture-model", "timeout_seconds": 30, "max_output_tokens": 200,
                      "_read_capabilities": [{"key": "invoices"}]}
            valid = OpenAIProvider().respond("bounded", "partial invoices", config)
            self.assertEqual(valid.lookups[0].arguments.status, "PARTIAL")
            self.assertEqual(create.call_count, 1)
            proposal["arguments"]["as_of"] = "2026-11-01"
            response.output_text = json.dumps(output)
            invalid = OpenAIProvider().respond("bounded", "partial invoices", config)
            self.assertIsNone(invalid.output)
            self.assertEqual(invalid.error, "invalid_response")
            self.assertEqual(invalid.input_tokens, 100)


def found(key, *rows, more=False):
    return {"capability": key, "items": list(rows), "more_matches": more, "note": "Scoped results"}


class TolerantReadUnitTests(unittest.TestCase):
    def test_status_words_and_empty_catalogue_queries_are_normalised(self):
        unpaid = lookup("invoices", query="unpaid")
        self.assertEqual((unpaid.arguments.status, unpaid.arguments.query), ("UNPAID", ""))
        vendors = ReadLookup.model_validate({"capability": "parties", "arguments": {"query": "", "store_id": None, "limit": 5}})
        self.assertEqual(vendors.arguments.query, "")
        listing = lookup("parties")
        self.assertEqual((type(listing.arguments).__name__, listing.arguments.query), ("LookupArguments", ""))
        suppliers = ReadLookup.model_validate({"capability": "parties", "arguments": {"query": "", "store_id": None, "limit": 10,
            "from_date": None, "to_date": None, "as_of": None, "status": "vendor"}})
        self.assertEqual((type(suppliers.arguments).__name__, suppliers.arguments.query), ("LookupArguments", "vendor"))
        with self.assertRaises(ValidationError):
            lookup("refunds", status="UNPAID")

    def test_plural_typo_store_and_listing_fallbacks_stay_read_only(self):
        from app.ai.capabilities import execute_read
        bottle = {"id": str(uuid4()), "name": "Copper bottle", "stock": Decimal("90")}
        def plural(_db, _identity, request):
            return found("products", bottle) if request.arguments.query == "copper bottle" else found("products")
        with patch("app.ai.capabilities.execute_lookup", side_effect=plural):
            result = execute_read(None, {}, ReadLookup.model_validate(
                {"capability": "products", "arguments": {"query": "copper bottles", "store_id": None, "limit": 5}}))
        self.assertEqual(result["items"], [bottle])
        def typo(_db, _identity, request):
            return found("products", bottle) if request.arguments.query in {"cop", "bot"} else found("products")
        with patch("app.ai.capabilities.execute_lookup", side_effect=typo):
            result = execute_read(None, {}, ReadLookup.model_validate(
                {"capability": "products", "arguments": {"query": "coper botle", "store_id": None, "limit": 5}}))
        self.assertEqual(result["items"], [bottle])
        self.assertIn("closest", result["fallback_note"])
        account = {"account_id": str(uuid4()), "account_name": "Main Account", "balance": Decimal("4000")}
        def accounts(_db, _identity, request):
            return found("accounts", account) if not request.arguments.query else found("accounts")
        with patch("app.ai.capabilities.execute_lookup", side_effect=accounts):
            result = execute_read(None, {}, lookup("accounts", query="cash"))
        self.assertEqual(result["items"], [account])
        self.assertIn("listed instead", result["fallback_note"])
        def store(_db, _identity, request):
            if request.arguments.store_id:
                raise HTTPException(status_code=404)
            return found("products", bottle)
        with patch("app.ai.capabilities.execute_lookup", side_effect=store):
            result = execute_read(None, {}, ReadLookup.model_validate({"capability": "products", "arguments": {
                "query": "copper bottle", "store_id": str(uuid4()), "limit": 5}}))
        self.assertEqual(result["items"], [bottle])
        self.assertIn("store was not recognised", result["fallback_note"])

    def test_readable_facts_hide_ids_sum_complete_sets_and_stay_bounded(self):
        from app.ai.capabilities import is_read_answer, readable_lookup, rupees
        rows = [{"id": str(uuid4()), "invoice_number": f"I{index}", "customer_id": str(uuid4()), "total": Decimal("10.50"),
                 "invoice_date": date(2026, 11, 14), "collection_status": "BAD_DEBT", "is_draft": False}
                for index in range(3)]
        text_out = readable_lookup({**found("invoices", *rows), "query": "", "fallback_note": ""}, 2000)
        self.assertTrue(is_read_answer(text_out))
        self.assertIn("From your Tenali records — Invoices (3)", text_out)
        self.assertIn("• I0: total ₹10.50 · collection status bad debt · invoice date 14 Nov 2026", text_out)
        self.assertIn("Total: ₹31.50", text_out)
        self.assertNotIn(rows[0]["id"], text_out)
        self.assertNotIn("draft", text_out)
        self.assertNotIn("{", text_out)
        self.assertEqual((rupees(Decimal("1234567.5")), rupees(Decimal("-400"))), ("₹12,34,567.50", "-₹400.00"))
        accounts = [{"account_id": str(uuid4()), "account_name": "Main Account", "account_type": "bank",
                     "is_company_account": False, "opening_balance": Decimal("1000.00"), "current_balance": Decimal("4000.00"),
                     "transaction_count": 5}]
        self.assertIn("• Main Account: current balance ₹4,000.00 · account type bank · opening balance ₹1,000.00 · "
                      "transaction count 5", readable_lookup({**found("accounts", *accounts), "query": ""}, 2000))
        partial = readable_lookup({**found("invoices", *rows, more=True), "query": ""}, 2000)
        self.assertNotIn("Total:", partial)
        self.assertIn("(3+)", partial)
        many = [{"name": f"Product {index}", "description": "x" * 80} for index in range(40)]
        bounded = readable_lookup({**found("products", *many), "query": "p"}, 600)
        self.assertLessEqual(len(bounded), 640)
        self.assertIn("Showing the first few only", bounded)

    def test_descriptive_words_become_filters_only_after_the_literal_search_finds_nothing(self):
        from app.ai.capabilities import execute_read, interpret_lookup
        today = date(2026, 11, 14)  # Saturday
        sales, _, notes = interpret_lookup(lookup("invoices", query="last week sales total"), today)
        self.assertEqual((sales.arguments.query, sales.arguments.from_date, sales.arguments.to_date),
                         ("", date(2026, 11, 2), date(2026, 11, 8)))
        self.assertIn("Last week", notes[0])
        bills, _, _ = interpret_lookup(lookup("purchases", query="pending supplier bills"), today)
        self.assertEqual((bills.arguments.query, bills.arguments.status), ("", "UNPAID"))
        refunds, _, _ = interpret_lookup(lookup("refunds", query="due refunds today"), today)
        self.assertEqual((refunds.arguments.status, refunds.arguments.from_date), ("PENDING", today))
        settled, _, _ = interpret_lookup(lookup("invoices", query="paid invoices this month"), today)
        self.assertEqual((settled.arguments.status, settled.arguments.from_date), ("SETTLED", date(2026, 11, 1)))
        vendors, party_type, _ = interpret_lookup(lookup("parties", query="vendors"), today)
        self.assertEqual((vendors.arguments.query, party_type, vendors.arguments.limit), ("", "vendor", 10))
        rows = [{"id": "1", "name": "Tiger Glass", "party_type": "vendor"}, {"id": "2", "name": "Vijay", "party_type": "customer"}]
        def parties(_db, _identity, request):
            return found("parties", *rows) if not request.arguments.query else found("parties")
        with patch("app.ai.capabilities.execute_lookup", side_effect=parties):
            result = execute_read(None, {}, lookup("parties", query="vendor"))
        self.assertEqual([row["name"] for row in result["items"]], ["Tiger Glass"])
        named = {"id": "3", "name": "Bill Traders", "party_type": "vendor"}
        with patch("app.ai.capabilities.execute_lookup", return_value=found("parties", named)) as execute:
            result = execute_read(None, {}, lookup("parties", query="bill traders"))
        self.assertEqual((result["items"], execute.call_count), ([named], 1))

    def test_today_as_of_means_current_and_journal_words_become_dates(self):
        from app.ai.capabilities import execute_read
        from app.ai.schemas import business_today
        today = business_today()
        current = ReadLookup.model_validate({"capability": "receivables", "arguments": {
            "query": "", "store_id": None, "limit": 5, "from_date": None, "to_date": None, "as_of": today.isoformat(), "status": "UNPAID"}})
        self.assertIsNone(current.arguments.as_of)
        with self.assertRaises(ValidationError):
            lookup("receivables", as_of=date(2020, 1, 1))
        seen = []
        def journal(_db, _identity, request):
            seen.append(request.arguments)
            return found("account_journal", {"period_key": str(today), "amount": Decimal("1")})
        with patch("app.ai.capabilities.execute_lookup", side_effect=journal):
            execute_read(None, {}, lookup("account_journal", query="sales today"))
        self.assertEqual((len(seen), seen[0].query, seen[0].from_date, seen[0].to_date), (1, "", today, today))
        customers = [{"id": "1", "name": "test customer", "party_type": "customer"},
                     {"id": "2", "name": "Vijay", "party_type": "customer"}, {"id": "3", "name": "Tiger", "party_type": "vendor"}]
        def parties(_db, _identity, request):
            rows = [row for row in customers if request.arguments.query in row["name"]]
            return found("parties", *rows)
        with patch("app.ai.capabilities.execute_lookup", side_effect=parties):
            result = execute_read(None, {}, lookup("parties", query="customers"))
        self.assertEqual([row["name"] for row in result["items"]], ["test customer", "Vijay"])


@unittest.skipUnless(os.getenv("TENALI_AI_ISOLATED_DB"), "Synthetic finance tests require an isolated PostgreSQL database")
class BusinessReadDatabaseTests(TenantDatabaseCase):
    def setUp(self):
        from app.core.database import engine
        expected = os.environ["TENALI_AI_ISOLATED_DB"]
        if not expected.startswith("tenali_ai_read_test_"):
            raise RuntimeError("Refusing synthetic finance tests without an isolated test database")
        with engine.connect() as db:
            if db.execute(text("select current_database()")).scalar_one() != expected:
                raise RuntimeError("Refusing synthetic finance tests on a different database")
        super().setUp()
        apply_ai_business_read_migration(self.connection)
        self.stack.enter_context(patch.dict(os.environ, {"OPENAI_API_KEY": "mock-only", "OPENAI_ALLOWED_MODELS": "fixture-model"}))
        owner, _, _ = self.register("business-read")
        self.identity = owner["user"]
        self.company = self.identity["company_id"]
        read_fixtures.ReadDatabaseTests.enable(self, self.identity, tuple(REGISTRY))
        self.seed()

    def seed(self):
        with self.factory() as db:
            params = {"company": self.company}
            self.shop = db.execute(text("select id from stores where company_id=:company and is_default"), params).scalar_one()
            self.hidden = db.execute(text("""insert into stores(company_id,code,name,kind,holds_stock)
                values(:company,'SECRET','Secret store','offline',true) returning id"""), params).scalar_one()
            self.party = db.execute(text("""insert into parties(company_id,party_type,legal_name)
                values(:company,'customer_vendor','Fixture Party') returning id"""), params).scalar_one()
            self.account = db.execute(text("""insert into accounts(company_id,nickname,account_type,opening_balance)
                values(:company,'Fixture Cash','CASH',100) returning id"""), params).scalar_one()
            params.update(party=self.party, account=self.account)
            self.invoices = []
            for index, store in enumerate((self.shop, self.hidden)):
                values = {**params, "store": store, "number": f"Fixture INV {index}"}
                invoice = db.execute(text("""insert into invoices(company_id,store_id,invoice_number,customer_party_id,
                    invoice_date,total,amount_received,collection_status)
                    values(:company,:store,:number,:party,'2026-11-01',100,25,'PARTIAL') returning id"""), values).scalar_one()
                self.invoices.append(invoice)
                db.execute(text("""insert into purchases(company_id,store_id,vendor_party_id,bill_number,purchase_date,
                    total,amount_paid,payment_status) values(:company,:store,:party,:number,'2026-11-01',200,50,'PARTIAL')"""), values)
                db.execute(text("""insert into receivables(company_id,party_id,invoice_id,reference,amount_due,amount_received,status,due_date)
                    values(:company,:party,:invoice,:number,100,25,'PARTIAL','2026-11-15')"""), {**values, "invoice": invoice})
                original = db.execute(text("""insert into account_transactions(company_id,to_account_id,amount,transaction_date,category)
                    values(:company,:account,25,'2026-11-01','business_billing') returning id"""), params).scalar_one()
                reversal = db.execute(text("""insert into account_transactions(company_id,from_account_id,amount,transaction_date,
                    reversal_of_transaction_id) values(:company,:account,25,'2026-11-02',:original) returning id"""),
                    {**params, "original": original}).scalar_one()
                db.execute(text("""insert into refund_settlements(company_id,direction,document_type,document_id,
                    document_number,party_id,original_transaction_id,reversal_transaction_id,amount,created_at)
                    values(:company,'PAY_CUSTOMER','invoice',:invoice,:number,:party,:original,:reversal,25,'2026-11-02')"""),
                    {**values, "invoice": invoice, "original": original, "reversal": reversal})
            db.execute(text("""insert into receivables(company_id,party_id,reference,amount_due,due_date)
                values(:company,:party,'Fixture standalone',50,'2026-11-15')"""), params)
            db.execute(text("""insert into borrowings(company_id,party_id,direction,amount,transaction_date)
                values(:company,:party,'borrow',80,'2026-11-01'),(:company,:party,'repay',20,'2026-11-02')"""), params)
            db.execute(text("""insert into borrowings(company_id,party_id,direction,amount,transaction_date,source_transaction_id)
                values(:company,:party,'borrow',999,'2026-11-01',:original)"""), {**params, "original": original})
            db.execute(text("""insert into accounting_period_locks(company_id,period_start,period_end,reason)
                values(:company,'2026-10-01','2026-10-31','Fixture close')"""), params)
            product = db.execute(text("""insert into products(company_id,portal_product_id,name,reorder_enabled,reorder_level,reorder_target)
                values(:company,'fixture-read','Fixture Lamp',true,10,20) returning id"""), params).scalar_one()
            self.product = product
            for store, quantity in ((self.shop, 3), (self.hidden, 40)):
                db.execute(text("""insert into stock_balances(company_id,product_id,store_id,quantity)
                    values(:company,:product,:store,:quantity)"""), {**params, "product": product, "store": store, "quantity": quantity})
            db.commit()

    def test_all_ten_reads_execute_without_business_writes_and_match_existing_semantics(self):
        with self.factory() as db:
            db.info["tenant_context"] = self.identity
            identity = current_identity(db, self.identity)
            statements = []
            from sqlalchemy import event
            connection = db.connection()
            def capture(_connection, _cursor, statement, _parameters, _context, _many):
                statements.append(statement)
            event.listen(connection, "before_cursor_execute", capture)
            try:
                results = {key: execute_lookup(db, identity, lookup(key, query="Fixture")) for key in
                           ("accounts", "transactions", "invoices", "purchases", "receivables", "refunds",
                            "borrowings", "reorder", "reconciliation", "period_locks")}
                self.assertEqual(results["accounts"]["items"][0]["current_balance"], Decimal("100"))
                self.assertEqual(results["borrowings"]["items"][0]["net_outstanding"], Decimal("60"))
                self.assertEqual(results["invoices"]["items"][0]["amount_received"], Decimal("25"))
                self.assertEqual(results["purchases"]["items"][0]["balance_amount"], Decimal("150"))
                self.assertEqual({row["balance_amount"] for row in results["receivables"]["items"]},
                                 {Decimal("50"), Decimal("75")})
                self.assertTrue(results["receivables"]["more_matches"])
                self.assertEqual(results["reorder"]["items"], [])
                self.assertEqual(len(results["reconciliation"]["items"]), 2)
                self.assertEqual(len(results["period_locks"]["items"]), 1)
                self.assertFalse(any(sql.lstrip().lower().startswith(("insert", "update", "delete", "create", "alter", "drop"))
                                     for sql in statements), statements)
                self.assertFalse(any("i.document_data" in sql or "p.line_items" in sql for sql in statements))
            finally:
                event.remove(connection, "before_cursor_execute", capture)

    def test_store_scope_excludes_hidden_documents_standalone_receivables_and_ledgers(self):
        with self.factory() as db:
            db.execute(text("""update tenant_memberships set role='staff',store_ids=array[cast(:store as uuid)]
                where company_id=:company and user_id=:user"""),
                {"company": self.company, "user": self.identity["user_id"], "store": self.shop})
            db.commit()
        with self.factory() as db:
            db.info["tenant_context"] = self.identity
            identity = current_identity(db, self.identity)
            visible = {item["key"] for item in available_capabilities(db, identity)}
            self.assertTrue({"accounts", "transactions", "borrowings"}.isdisjoint(visible))
            for key in ("invoices", "purchases", "receivables", "refunds"):
                result = execute_lookup(db, identity, lookup(key))
                self.assertEqual(len(result["items"]), 1, key)
                with self.assertRaises(HTTPException) as error:
                    execute_lookup(db, identity, lookup(key, store_id=self.hidden))
                self.assertEqual(error.exception.status_code, 403)
            self.assertEqual(execute_lookup(db, identity, lookup("reorder"))["items"][0]["stock_qty"], Decimal("3"))
            self.assertEqual(execute_lookup(db, identity, lookup("reconciliation"))["items"][0]["balance_quantity"], Decimal("3"))
            for key in ("accounts", "transactions", "borrowings"):
                with self.assertRaises(HTTPException):
                    execute_lookup(db, identity, lookup(key))
            no_stores = {**identity, "store_ids": []}
            for key in ("invoices", "purchases", "receivables", "refunds", "reorder", "reconciliation"):
                self.assertEqual(execute_lookup(db, no_stores, lookup(key))["items"], [], key)

    def test_date_status_bounds_and_existing_lists_preserved(self):
        with self.factory() as db:
            db.info["tenant_context"] = self.identity
            identity = current_identity(db, self.identity)
            self.assertEqual(len(execute_lookup(db, identity, lookup("invoices", status="PARTIAL"))["items"]), 2)
            self.assertEqual(execute_lookup(db, identity, lookup("invoices", status="CANCELLED"))["items"], [])
            self.assertEqual(execute_lookup(db, identity, lookup("purchases", from_date=date(2026, 11, 2)))["items"], [])
            self.assertEqual(execute_lookup(db, identity, lookup("refunds", status="SETTLED"))["items"], [])
            self.assertEqual(execute_lookup(db, identity, lookup("receivables", to_date=date(2026, 11, 14)))["items"], [])
            self.assertEqual(execute_lookup(db, identity, lookup("period_locks", as_of=date(2026, 11, 1)))["items"], [])
            self.assertEqual(len(execute_lookup(db, identity, lookup("period_locks", as_of=date(2026, 10, 31)))["items"]), 1)
            self.assertEqual(len(BillingService(db).list_invoices(self.company)["items"]), 2)
            self.assertIn("document_data", BillingService(db).list_invoices(self.company)["items"][0])
            self.assertEqual(len(PurchasesService(db).list_purchases(self.company)["items"]), 2)
            self.assertIn("line_items", PurchasesService(db).list_purchases(self.company)["items"][0])
            self.assertEqual(len(CollectionsService(db).list_receivables(self.company)["items"]), 3)
            self.assertEqual(AccountsService(db).account_tally(self.company)["total_current_balance"], 100.0)
            historical = execute_lookup(db, identity, lookup("accounts", query="Fixture", as_of=date(2026, 11, 1)))
            self.assertEqual(historical["items"][0]["current_balance"], Decimal("150"))
            reversed_balance = execute_lookup(db, identity, lookup("accounts", query="Fixture", as_of=date(2026, 11, 2)))
            self.assertEqual(reversed_balance["items"][0]["current_balance"], Decimal("100"))

    def test_other_tenant_cannot_read_fixture_records(self):
        other, _, _ = self.register("business-read-other")
        with self.factory() as db:
            db.info["tenant_context"] = other["user"]
            identity = current_identity(db, other["user"])
            for key in ("accounts", "transactions", "invoices", "purchases", "receivables",
                        "refunds", "borrowings", "reorder", "reconciliation", "period_locks"):
                result = execute_lookup(db, identity, lookup(key, query="Fixture"))
                self.assertEqual(result["items"], [], key)

    def test_financial_chat_reserves_schema_and_replays_without_another_provider_call(self):
        with self.factory() as db:
            db.info["tenant_context"] = self.identity
            service = AssistantService(db, self.identity)
            conversation = service.create(ConversationCreate())
            db.execute(text("""insert into ai_messages(company_id,user_id,conversation_id,client_key,role,content,status)
                values(:company,:user,:conversation,:key,'assistant',:content,'completed')"""),
                {"company": self.company, "user": self.identity["user_id"], "conversation": conversation["id"],
                 "key": uuid4(), "content": "\u0915" * 11900})
            db.commit()
            payload = MessageCreate(content="Show partial invoices", client_key=uuid4())
            response = ProviderResult(AssistantOutput(reply="Checking partial invoices.", clarification=None),
                100, 0, 30, "mock-financial", lookups=(lookup("invoices", status="PARTIAL"),))
            with patch("app.ai.service.OpenAIProvider.respond", return_value=response) as provider:
                result = service.send(conversation["id"], payload)
                self.assertEqual(result["items"][0]["status"], "completed")
                self.assertIn("From your Tenali records", result["items"][1]["content"])
                self.assertIn("Fixture INV", result["items"][1]["content"])
                self.assertLessEqual(len(result["items"][1]["content"]), 12000)
                offered = provider.call_args.args[2]["_read_capabilities"]
                self.assertEqual(len(offered), 16)
                self.assertNotIn("\\u0915" * 100, provider.call_args.args[0])
                service.send(conversation["id"], payload)
                self.assertEqual(provider.call_count, 1)
            self.assertEqual(service.usage()["personal"]["tokens"], 130)
