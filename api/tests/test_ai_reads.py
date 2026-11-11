import json
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.ai.capabilities import REGISTRY, available_capabilities, current_identity, execute_lookup, format_lookup
from app.ai.provider import OpenAIProvider, ProviderResult
from app.ai.schemas import AssistantOutput, ConversationCreate, LookupArguments, MessageCreate, ReadAssistantOutput, ReadLookup
from app.ai.service import AssistantService
from app.services.inventory_service import InventoryService
from app.services.masters_service import MastersService
from app.services.parties_service import PartiesService
from app.services.stores_service import StoresService
from schema_support import apply_ai_read_migration
from test_tenancy import TenantDatabaseCase
import test_feature_controls as feature_fixtures


def product_lookup(query="lamp", store_id=None, limit=2):
    return ReadLookup(capability="products", arguments=LookupArguments(query=query, store_id=store_id, limit=limit))


class ReadUnitTests(unittest.TestCase):
    def test_proposals_are_strict_bounded_and_cannot_supply_identity_or_sql(self):
        valid = {"reply": "Checking permitted stock.", "clarification": None,
                 "lookups": [product_lookup().model_dump(mode="json")]}
        self.assertEqual(len(ReadAssistantOutput.model_validate(valid).lookups), 1)
        for proposal in (
            {"capability": "sql", "arguments": valid["lookups"][0]["arguments"]},
            {"capability": "products", "arguments": {**valid["lookups"][0]["arguments"], "company_id": str(uuid4())}},
            {"capability": "products", "arguments": {**valid["lookups"][0]["arguments"], "limit": 11}},
            {"capability": "products", "arguments": {**valid["lookups"][0]["arguments"], "query": "x" * 81}},
        ):
            with self.assertRaises(ValidationError):
                ReadAssistantOutput.model_validate({**valid, "lookups": [proposal]})
        with self.assertRaises(ValidationError):
            ReadAssistantOutput.model_validate({**valid, "lookups": valid["lookups"] * 3})

    def test_provider_proposes_reads_in_one_metered_call_without_executable_tools(self):
        response = SimpleNamespace(status="completed", id="mock-read",
            output_text=json.dumps({"reply": "Checking permitted stock.", "clarification": None,
                                    "lookups": [product_lookup().model_dump(mode="json")]}),
            usage=SimpleNamespace(input_tokens=50, output_tokens=30, input_tokens_details=SimpleNamespace(cached_tokens=0)))
        with patch("app.ai.provider.OpenAI") as client:
            create = client.return_value.__enter__.return_value.responses.create
            create.return_value = response
            result = OpenAIProvider().respond("bounded context", "lamp stock", {
                "timeout_seconds": 30, "routine_model": "fixture", "max_output_tokens": 200,
                "_read_capabilities": [{"key": "products"}],
            })
            self.assertEqual(create.call_count, 1)
            self.assertNotIn("tools", create.call_args.kwargs)
            self.assertIn("lookups", create.call_args.kwargs["text"]["format"]["schema"]["properties"])
            self.assertEqual(result.lookups[0].capability, "products")
            self.assertEqual(result.input_tokens, 50)

    def test_projection_and_database_limit_do_not_upload_contact_details(self):
        identity = {"company_id": str(uuid4()), "role": "owner"}
        lookup = ReadLookup(capability="parties", arguments=LookupArguments(query="brass", store_id=None, limit=1))
        with patch("app.ai.capabilities.PartiesService") as service:
            service.return_value.list.return_value = {"items": [
                {"id": "one", "legal_name": "Brass", "phone": "private", "email": "private"},
                {"id": "two", "legal_name": "Brass Two"}]}
            result = execute_lookup(Mock(), identity, lookup)
            self.assertEqual(service.return_value.list.call_args.kwargs["limit"], 2)
            self.assertEqual(len(result["items"]), 1)
            self.assertTrue(result["more_matches"])
            self.assertNotIn("phone", result["items"][0])
            self.assertNotIn("email", result["items"][0])
        with self.assertRaises(HTTPException):
            execute_lookup(Mock(), {**identity, "role": "staff", "modules": ["inventory"]}, lookup)

    def test_output_size_is_measured_and_partial_results_are_explicit(self):
        result = {"capability": "products", "items": [{"name": "\u0915" * 4000}], "more_matches": False, "note": ""}
        formatted = format_lookup(result, 500)
        self.assertLessEqual(len(formatted), 550)
        self.assertIn('"more_matches": true', formatted)
        self.assertIn("narrow your query", formatted)

    def test_capability_policy_and_module_restrictions_filter_discovery(self):
        items = [{"key": key, "enabled": True, "compatible": True, "tenant_allowed": True,
                  "version": 1, "tenant_version": 1, "description": key} for key in REGISTRY]
        items[0]["enabled"] = False
        items[2]["compatible"] = False
        with patch("app.ai.capabilities.platform_capabilities", return_value={"items": items}):
            available = available_capabilities(Mock(), {"company_id": uuid4(), "role": "staff", "modules": ["inventory"]})
        self.assertEqual({item["key"] for item in available}, {"products", "brands", "categories", "reorder", "reconciliation",
            "product_details", "variants", "vendor_offers", "stock_transfers", "stock_movements", "movement_sources"})

    def test_revoked_or_unoffered_lookup_is_not_executed_but_usage_is_preserved(self):
        service = AssistantService(Mock(), {"company_id": uuid4(), "user_id": uuid4()})
        service.conversation = Mock(return_value={"status": "active"})
        service.require_enabled = Mock(return_value={"version": 1})
        result = ProviderResult(AssistantOutput(reply="Checking", clarification=None), 50, 0, 30, "mock",
                                lookups=(product_lookup(),))
        with patch("app.ai.service.current_identity", return_value=service.identity), \
             patch("app.ai.service.available_capabilities", return_value=[]), \
             patch("app.ai.service.execute_lookup") as execute:
            failed = service.read_results(uuid4(), uuid4(), result, [], {"version": 1})
            execute.assert_not_called()
            self.assertIsNone(failed.output)
            self.assertEqual(failed.error, "lookup_rejected")
            self.assertEqual(failed.input_tokens, 50)
            self.assertEqual(failed.output_tokens, 30)


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Rollback-only read fixtures; provider always mocked")
class ReadDatabaseTests(TenantDatabaseCase):
    def setUp(self):
        super().setUp()
        apply_ai_read_migration(self.connection)
        self.stack.enter_context(patch.dict(os.environ, {
            "OPENAI_API_KEY": "mock-only", "OPENAI_ALLOWED_MODELS": "fixture-model"}))

    def enable(self, identity, keys=("products", "stores", "parties", "hsn", "brands", "categories")):
        with self.factory() as db:
            db.execute(text("update ai_platform_settings set config=cast(:config as jsonb) where id=true"), {
                "config": json.dumps({"global_enabled": True, "routine_model": "fixture-model", "document_model": "fixture-model",
                                     "input_cost_per_million": "1", "output_cost_per_million": "2"})})
            db.execute(text("update tenant_feature_controls set platform_allowed=true where company_id=:company and feature_key='ai'"),
                       {"company": identity["company_id"]})
            db.execute(text("update ai_tenant_settings set tenant_enabled=true where company_id=:company"),
                       {"company": identity["company_id"]})
            for key in keys:
                db.execute(text("update ai_capabilities set enabled=true,schema_fingerprint=:hash where key=:key"),
                           {"hash": REGISTRY[key].fingerprint, "key": key})
                db.execute(text("""insert into ai_tenant_capabilities(company_id,capability_key,allowed)
                    values(:company,:key,true)"""), {"company": identity["company_id"], "key": key})
            db.commit()

    def scoped_service(self, db, identity):
        db.info["tenant_context"] = identity
        return AssistantService(db, identity)

    def test_scoped_product_stock_bounded_search_and_minimal_lookup_projections(self):
        owner, _, _ = self.register("ai-read-stock")
        other, _, _ = self.register("ai-read-other")
        identity = owner["user"]
        self.enable(identity)
        with self.factory() as db:
            company = identity["company_id"]
            shop = db.execute(text("select id from stores where company_id=:company and is_default"), {"company": company}).scalar_one()
            hidden = db.execute(text("""insert into stores(company_id,code,name,kind,holds_stock)
                values(:company,'HIDDEN','Hidden shop','offline',true) returning id"""), {"company": company}).scalar_one()
            product = db.execute(text("insert into products(company_id,portal_product_id,name,sku) values(:company,901,'Lamp brass','LAMP') returning id"),
                                 {"company": company}).scalar_one()
            db.execute(text("insert into products(company_id,portal_product_id,name,sku) values(:company,902,'Lamp silver','SILVER'),(:other,901,'Lamp secret','SECRET')"),
                       {"company": company, "other": other["user"]["company_id"]})
            for store, quantity in ((shop, 3), (hidden, 90)):
                db.execute(text("insert into stock_balances(company_id,product_id,store_id,quantity) values(:company,:product,:store,:quantity)"),
                           {"company": company, "product": product, "store": store, "quantity": quantity})
            db.execute(text("update tenant_memberships set role='staff',modules=array['inventory'],store_ids=array[cast(:store as uuid)] where company_id=:company and user_id=:user"),
                       {"company": company, "user": identity["user_id"], "store": shop})
            db.commit()
        with self.factory() as db:
            db.info["tenant_context"] = identity
            refreshed = current_identity(db, identity)
            self.assertEqual({item["key"] for item in available_capabilities(db, refreshed)}, {"stores", "products", "brands", "categories"})
            found = execute_lookup(db, refreshed, product_lookup(limit=1))
            self.assertEqual(found["items"][0]["stock_qty"], Decimal("3"))
            self.assertTrue(found["more_matches"])
            self.assertNotIn("secret", json.dumps(found, default=str).lower())
            with self.assertRaises(HTTPException) as error:
                execute_lookup(db, refreshed, product_lookup(store_id=hidden))
            self.assertEqual(error.exception.status_code, 403)
            self.assertEqual(db.execute(text("select count(*) from ai_tenant_capabilities")).scalar_one(), 6)

    def test_chat_appends_verified_facts_and_replay_does_not_repeat_reads_or_provider(self):
        owner, _, _ = self.register("ai-read-chat")
        identity = owner["user"]
        self.enable(identity, ("products",))
        with self.factory() as db:
            db.execute(text("insert into products(company_id,portal_product_id,name,sku) values(:company,901,'Lamp fixture','LAMP')"),
                       {"company": identity["company_id"]})
            db.commit()
        with self.factory() as db:
            service = self.scoped_service(db, identity)
            conversation = service.create(ConversationCreate())
            payload = MessageCreate(content="Find lamp stock", client_key=uuid4())
            response = ProviderResult(AssistantOutput(reply="Checking permitted stock.", clarification=None),
                                      50, 0, 30, "mock-read", lookups=(product_lookup(),))
            with patch("app.ai.service.OpenAIProvider.respond", return_value=response) as provider:
                sent = service.send(conversation["id"], payload)
                self.assertEqual(sent["items"][0]["status"], "completed")
                self.assertIn("Verified Tenali lookup", sent["items"][1]["content"])
                self.assertIn("Lamp fixture", sent["items"][1]["content"])
                self.assertLessEqual(len(sent["items"][1]["content"]), 12000)
                service.send(conversation["id"], payload)
                self.assertEqual(provider.call_count, 1)
            self.assertEqual(db.execute(text("select count(*) from ai_audit_events where event_type='READ_PRODUCTS_COMPLETED'")).scalar_one(), 1)
            self.assertEqual(service.usage()["personal"]["tokens"], 80)

    def test_policy_revocation_after_provider_prevents_read_and_keeps_usage(self):
        owner, _, _ = self.register("ai-read-revoke")
        identity = owner["user"]
        self.enable(identity, ("products",))
        with self.factory() as db:
            service = self.scoped_service(db, identity)
            conversation = service.create(ConversationCreate())
            def provider(*_args):
                with self.factory() as admin:
                    admin.execute(text("update ai_capabilities set enabled=false,version=version+1 where key='products'"))
                    admin.commit()
                return ProviderResult(AssistantOutput(reply="Checking.", clarification=None),
                                      50, 0, 30, "mock-revoked", lookups=(product_lookup(),))
            with patch("app.ai.service.OpenAIProvider.respond", side_effect=provider), \
                 patch("app.ai.service.execute_lookup") as execute:
                sent = service.send(conversation["id"], MessageCreate(content="Find lamps", client_key=uuid4()))
                execute.assert_not_called()
                self.assertEqual(sent["items"][0]["status"], "failed")
                self.assertEqual(sent["items"][0]["error_code"], "lookup_rejected")
                self.assertEqual(service.usage()["personal"]["tokens"], 80)

    def test_changed_contract_blocks_only_that_capability_and_platform_routes_require_admin(self):
        owner, cookies, _ = self.register("ai-read-contract")
        identity = owner["user"]
        self.enable(identity, ("products", "stores"))
        with self.factory() as db:
            db.execute(text("update ai_capabilities set schema_fingerprint='outdated' where key='products'"))
            db.commit()
        self.use_cookies(cookies)
        response = self.client.get("/ai/capabilities")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["key"] for item in response.json()["items"]], ["stores"])
        denied = self.client.patch("/platform/ai/capabilities/stores", json={
            "enabled": True, "approve_contract": True, "expected_version": 1}, headers=self.headers(cookies))
        self.assertIn(denied.status_code, (401, 403))

    def test_platform_review_tenant_grants_and_stale_versions(self):
        owner, _, _ = self.register("ai-read-admin")
        company = owner["user"]["company_id"]
        _, cookies = feature_fixtures.FeatureControlDatabaseTests.platform_session(self)
        self.use_cookies(cookies)
        headers = {"Origin": "http://localhost", "X-CSRF-Token": cookies["tenali_platform_csrf"]}
        path = "/platform/ai/capabilities/products"
        unreviewed = self.client.patch(path, json={"enabled": True, "expected_version": 1}, headers=headers)
        self.assertEqual(unreviewed.status_code, 409, unreviewed.text)
        approved = self.client.patch(path, json={"enabled": True, "approve_contract": True, "expected_version": 1}, headers=headers)
        self.assertEqual(approved.status_code, 200, approved.text)
        product = next(item for item in approved.json()["items"] if item["key"] == "products")
        self.assertTrue(product["compatible"])
        self.assertTrue(product["enabled"])
        self.assertEqual(self.client.patch(path, json={"enabled": False, "expected_version": 1}, headers=headers).status_code, 409)
        tenant = f"/platform/ai/tenants/{company}/capabilities/products"
        grant = self.client.patch(tenant, json={"allowed": True, "expected_version": 0}, headers=headers)
        self.assertEqual(grant.status_code, 200, grant.text)
        self.assertTrue(next(item for item in grant.json()["items"] if item["key"] == "products")["tenant_allowed"])
        self.assertEqual(self.client.patch(tenant, json={"allowed": False, "expected_version": 0}, headers=headers).status_code, 409)
        invalid = self.client.patch("/platform/ai/capabilities/arbitrary_sql", json={
            "enabled": True, "approve_contract": True, "expected_version": 1}, headers=headers)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.client.get(f"/platform/ai/capabilities?company_id={uuid4()}").status_code, 404)

    def test_remaining_adapters_are_bounded_and_existing_lists_preserved(self):
        owner, _, _ = self.register("ai-read-lists")
        identity = owner["user"]
        self.enable(identity)
        company = identity["company_id"]
        with self.factory() as db:
            for index in range(12):
                params = {"company": company, "name": f"Brass {index:02}", "code": str(9000 + index)}
                db.execute(text("""insert into parties(company_id,party_type,legal_name,phone,address)
                    values(:company,'vendor',:name,'private contact','private address')"""), params)
                db.execute(text("""insert into hsn_masters(company_id,code,description,gst_rate)
                    values(:company,:code,:name,18)"""), params)
                db.execute(text("insert into brands(company_id,code,name) values(:company,:code,:name)"), params)
                db.execute(text("insert into product_categories(company_id,code,name) values(:company,:code,:name)"), params)
            db.commit()
        with self.factory() as db:
            db.info["tenant_context"] = identity
            refreshed = current_identity(db, identity)
            for key in ("parties", "hsn", "brands", "categories"):
                result = execute_lookup(db, refreshed, ReadLookup(
                    capability=key, arguments=LookupArguments(query="Brass", store_id=None, limit=1)))
                self.assertEqual(len(result["items"]), 1)
                self.assertTrue(result["more_matches"])
                self.assertNotIn("private contact", json.dumps(result, default=str))
                self.assertNotIn("private address", json.dumps(result, default=str))
            self.assertEqual(len(PartiesService(db).list(company, search="Brass")["items"]), 12)
            self.assertEqual(len(MastersService(db).list_hsn(company, search="Brass")["items"]), 12)
            self.assertEqual(len(InventoryService(db, company).master_entries("brands")["items"]), 12)
            self.assertEqual(len(InventoryService(db, company).master_entries("categories")["items"]), 12)
            store = StoresService(db, company).list_stores()["items"][0]
            lookup = ReadLookup(capability="stores", arguments=LookupArguments(query=store["code"], store_id=None, limit=1))
            self.assertEqual(len(execute_lookup(db, refreshed, lookup)["items"]), 1)
