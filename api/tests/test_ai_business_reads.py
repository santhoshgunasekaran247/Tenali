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
            ReadLookup.model_validate({"capability": "products", "arguments": args})

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
                self.assertIn("Verified Tenali lookup", result["items"][1]["content"])
                self.assertIn("Fixture INV", result["items"][1]["content"])
                self.assertLessEqual(len(result["items"][1]["content"]), 12000)
                offered = provider.call_args.args[2]["_read_capabilities"]
                self.assertEqual(len(offered), 16)
                self.assertNotIn("\\u0915" * 100, provider.call_args.args[0])
                service.send(conversation["id"], payload)
                self.assertEqual(provider.call_count, 1)
            self.assertEqual(service.usage()["personal"]["tokens"], 130)
