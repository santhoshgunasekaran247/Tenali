import json
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.ai.provider import OpenAIProvider, ProviderResult, estimated_cost
from app.ai.actions import ACTIONS, DraftProposal
from app.ai.schemas import AssistantOutput, ConversationCreate, ConversationUpdate, LookupArguments, MessageCreate, ReadLookup
from app.ai.service import AssistantService, MAX_CONTEXT_BYTES, conversation_title, draft_status, resolve_draft_references
from schema_support import apply_ai_read_migration
from test_tenancy import TenantDatabaseCase


class AssistantUnitTests(unittest.TestCase):
    def test_conversation_title_is_short_and_collapses_whitespace(self):
        self.assertEqual(conversation_title("  Create a\n purchase  "), "Create a purchase")
        self.assertEqual(conversation_title("x" * 80), "x" * 57 + "...")

    def test_named_draft_references_require_unique_exact_lookup(self):
        store_id, other_id = str(uuid4()), str(uuid4())
        proposal = DraftProposal(action="purchase_create", target_id=None,
            payload_json=json.dumps({"store_id": "Main Store", "account_id": "Main Account", "lines": [{"product_id": "Copper Tumbler"}]}))
        lookup = ReadLookup(capability="stores", arguments=LookupArguments(query="Main Store", store_id=None, limit=3))
        facts = {"more_matches": False, "items": [{"id": store_id, "name": "Main store", "code": "MAIN"}]}
        resolved, unresolved = resolve_draft_references(proposal, [(lookup, facts)])
        values = json.loads(resolved.payload_json)
        self.assertEqual(values["store_id"], store_id)
        self.assertNotIn("account_id", values)
        self.assertNotIn("product_id", values["lines"][0])
        self.assertEqual(unresolved, ["account", "product"])
        for ambiguous in ({**facts, "more_matches": True},
                          {"more_matches": False, "items": [facts["items"][0], {"id": other_id, "name": "Main Store"}]}):
            resolved, unresolved = resolve_draft_references(proposal, [(lookup, ambiguous)])
            self.assertNotIn("store_id", json.loads(resolved.payload_json))
            self.assertIn("store", unresolved)
        different_query = lookup.model_copy(update={"arguments": lookup.arguments.model_copy(update={"query": "Main"})})
        resolved, _ = resolve_draft_references(proposal, [(different_query, facts)])
        self.assertNotIn("store_id", json.loads(resolved.payload_json))

    def test_named_target_requires_unique_product_lookup(self):
        product_id = uuid4()
        proposal = DraftProposal(action="stock_adjust", target_id="Copper Tumbler", payload_json="{}")
        lookup = ReadLookup(capability="products", arguments=LookupArguments(query="Copper Tumbler", store_id=None, limit=3))
        facts = {"more_matches": False, "items": [{"id": str(product_id), "name": "Copper Tumbler", "sku": None}]}
        resolved, unresolved = resolve_draft_references(proposal, [(lookup, facts)])
        self.assertEqual(resolved.target_id, product_id)
        self.assertEqual(unresolved, [])
        unresolved_proposal, unresolved = resolve_draft_references(proposal, [(lookup, {**facts, "more_matches": True})])
        self.assertIsNone(unresolved_proposal.target_id)
        self.assertEqual(unresolved, ["target"])
        missing, unresolved = resolve_draft_references(proposal.model_copy(update={"target_id": None}), [])
        self.assertIsNone(missing.target_id)
        self.assertEqual(unresolved, ["target"])

    def test_draft_status_distinguishes_saved_drafts_from_chat(self):
        self.assertEqual(draft_status(None), "No draft was saved in this reply.")
        self.assertEqual(draft_status("party_create"),
                         "Draft saved for review: party create. No business records have been changed.")

    def test_finish_reports_only_successfully_saved_drafts(self):
        for proposal in (None, DraftProposal(action="party_create", target_id=None, payload_json='{"legal_name":"Tiger Copper"}')):
            db = MagicMock()
            reservation = {"input_rate": Decimal("1"), "output_rate": Decimal("1"), "model": "fixture"}
            conversation = {"status": "active", "expires_at": datetime.max.replace(tzinfo=timezone.utc)}
            db.execute.return_value.mappings.return_value.one.side_effect = [reservation, conversation]
            service = AssistantService(db, {"company_id": uuid4(), "user_id": uuid4()})
            service.lock_conversation = Mock()
            service.require_enabled = Mock(return_value={"version": 1})
            service.audit = Mock()
            action = {"key": "party_create"}
            result = ProviderResult(AssistantOutput(reply="Ready.", clarification=None), 10, 0, 5, "fixture", draft=proposal)
            with patch("app.ai.service.lock_policy"), patch("app.ai.service.current_identity", return_value=service.identity), \
                 patch("app.ai.service.available_actions", return_value=[action]), patch("app.ai.service.DraftService.create") as create:
                service.finish(uuid4(), uuid4(), uuid4(), uuid4(), result, offered_actions=[action], reserved_version=1)
            self.assertEqual(create.call_count, int(proposal is not None))
            answers = [call.args[1]["answer"] for call in db.execute.call_args_list
                       if len(call.args) > 1 and "answer" in call.args[1]]
            self.assertEqual(len(answers), 1)
            self.assertIn(draft_status(proposal.action if proposal else None), answers[0])

    def test_strict_inputs_reject_identity_injection_and_empty_messages(self):
        for values in ({"content": " ", "client_key": uuid4()}, {"content": "x", "client_key": uuid4(), "company_id": uuid4()},
                       {"content": "x" * 4001, "client_key": uuid4()}):
            with self.assertRaises(ValidationError):
                MessageCreate(**values)
        with self.assertRaises(ValidationError):
            AssistantOutput.model_validate({"reply": "I paid", "clarification": None, "sql": "update accounts"})

    def test_cost_is_exact_and_cached_tokens_not_discounted_silently(self):
        self.assertEqual(estimated_cost(1000, 2000, Decimal("0.5"), Decimal("2")), Decimal("0.00450000"))

    def test_provider_uses_responses_without_tools_storage_or_retries(self):
        response = SimpleNamespace(
            status="completed", id="response-fixture", output_text=json.dumps({"reply": "Hello", "clarification": None}),
            usage=SimpleNamespace(input_tokens=20, output_tokens=10, input_tokens_details=SimpleNamespace(cached_tokens=3)),
        )
        config = {"timeout_seconds": 30, "routine_model": "fixture", "max_output_tokens": 200}
        with patch("app.ai.provider.OpenAI") as client:
            client.return_value.__enter__.return_value.responses.create.return_value = response
            result = OpenAIProvider().respond("context", "hello", config)
            options = client.return_value.__enter__.return_value.responses.create.call_args.kwargs
            self.assertFalse(options["store"])
            self.assertNotIn("tools", options)
            self.assertEqual(client.call_args.kwargs["max_retries"], 0)
            self.assertEqual(options["text"]["format"]["type"], "json_schema")
            self.assertEqual(result.cached_tokens, 3)
            self.assertEqual(result.output.reply, "Hello")

    def test_invalid_and_incomplete_provider_output_still_tracks_usage(self):
        for output, status in (('not-json', 'completed'), ('{"reply":"","clarification":null}', 'completed'), ("", "incomplete"),
                               (json.dumps({"reply": "x" * 11999, "clarification": "y"}), "completed")):
            response = SimpleNamespace(status=status, id="fixture", output_text=output,
                usage=SimpleNamespace(input_tokens=20, output_tokens=10, input_tokens_details=SimpleNamespace(cached_tokens=0)))
            with patch("app.ai.provider.OpenAI") as client:
                client.return_value.__enter__.return_value.responses.create.return_value = response
                result = OpenAIProvider().respond("context", "hello", {"timeout_seconds": 30, "routine_model": "fixture", "max_output_tokens": 200})
            self.assertIsNone(result.output)
            self.assertEqual(result.input_tokens, 20)
            self.assertIn(result.error, {"invalid_response", "response_incomplete"})

    def test_unicode_history_is_bounded_and_recent_context_survives(self):
        company, preferences, history = (Mock() for _ in range(3))
        company.mappings.return_value.one.return_value = {"company_name": "Example", "gst_registered": False}
        preferences.mappings.return_value.all.return_value = []
        history.mappings.return_value.all.return_value = [
            {"role": "user", "content": "Most recent clarification"},
            {"role": "assistant", "content": "\u0915" * 11900},
            {"role": "user", "content": "Oldest question"},
        ]
        db = Mock()
        db.execute.side_effect = [company, preferences, history]
        service = AssistantService(db, {"company_id": uuid4(), "user_id": uuid4()})
        context = service.context(uuid4())
        self.assertLessEqual(len(context.encode()), MAX_CONTEXT_BYTES)
        self.assertIn("Most recent clarification", context)
        self.assertIn("Oldest question", context)
        self.assertNotIn("\\u0915" * 100, context)

    def test_context_retains_older_lookup_and_user_facts_within_budget(self):
        company, preferences, history = (Mock() for _ in range(3))
        company.mappings.return_value.one.return_value = {"company_name": "Example", "gst_registered": False}
        preferences.mappings.return_value.all.return_value = []
        history.mappings.return_value.all.return_value = [
            {"role": "user", "content": "Yes, create the draft"},
            *[{"role": "assistant", "content": "Long reply " * 1000} for _ in range(15)],
            {"role": "assistant", "content": 'Verified Tenali lookup (read only): {"capability":"stores","items":[{"name":"Main Store"}]}'},
            {"role": "user", "content": "GST inclusive at 5 percent"},
        ]
        db = Mock()
        db.execute.side_effect = [company, preferences, history]
        context = AssistantService(db, {"company_id": uuid4(), "user_id": uuid4()}).context(uuid4())
        self.assertLessEqual(len(context.encode()), MAX_CONTEXT_BYTES)
        self.assertIn("Main Store", context)
        self.assertIn("GST inclusive at 5 percent", context)
        self.assertIn("Yes, create the draft", context)

    def test_context_prioritizes_user_facts_over_long_assistant_repetition(self):
        company, preferences, history = (Mock() for _ in range(3))
        company.mappings.return_value.one.return_value = {"company_name": "Example", "gst_registered": False}
        preferences.mappings.return_value.all.return_value = []
        history.mappings.return_value.all.return_value = [
            {"role": "user", "content": "Yes, proceed"},
            {"role": "assistant", "content": "Is this correct?"},
            *[{"role": "assistant", "content": "Repeated clarification " * 100} for _ in range(15)],
            {"role": "assistant", "content": 'Verified Tenali lookup (read only): {"capability":"stores","items":[{"name":"Main Store"}]}'},
            {"role": "user", "content": "Tiger Copper, GST inclusive at 5 percent"},
        ]
        db = Mock()
        db.execute.side_effect = [company, preferences, history]
        context = AssistantService(db, {"company_id": uuid4(), "user_id": uuid4()}).context(uuid4())
        self.assertIn("Tiger Copper, GST inclusive at 5 percent", context)
        self.assertIn("Main Store", context)
        self.assertIn("Is this correct?", context)
        self.assertIn("Yes, proceed", context)
        self.assertLess(context.index("Tiger Copper, GST inclusive at 5 percent"), context.index("Is this correct?"))
        self.assertLess(context.index("Is this correct?"), context.index("Yes, proceed"))
        self.assertLessEqual(len(context.encode()), MAX_CONTEXT_BYTES)

    def test_context_includes_only_offered_bounded_existing_drafts(self):
        company, preferences, history, drafts = (Mock() for _ in range(4))
        company.mappings.return_value.one.return_value = {"company_name": "Example", "gst_registered": False}
        preferences.mappings.return_value.all.return_value = []
        history.mappings.return_value.all.return_value = [{"role": "user", "content": "Create the vendor too"}]
        drafts.mappings.return_value.all.return_value = [
            {"action_key": "purchase_create", "status": "editing", "payload": {"lines": [{"description": "Copper Tumbler"}]}},
            {"action_key": "purchase_create", "status": "executed", "payload": {}, "successful_execution": {"id": "saved-record-id"}},
            {"action_key": "party_create", "status": "editing", "payload": {"legal_name": "Not offered"}},
            {"action_key": "purchase_create", "status": "editing", "payload": {"notes": "x" * 5000}},
        ]
        db = Mock()
        db.execute.side_effect = [company, preferences, history, drafts]
        action = ACTIONS["purchase_create"]
        actions = [{"key": action.key, "schema": action.schema.model_json_schema(), "target_required": False}]
        context = AssistantService(db, {"company_id": uuid4(), "user_id": uuid4()}).context(uuid4(), actions=actions)
        self.assertIn("Copper Tumbler", context)
        self.assertIn("saved-record-id", context)
        self.assertIn("Create the vendor too", context)
        self.assertNotIn("Not offered", context)
        self.assertNotIn("x" * 5000, context)
        self.assertLessEqual(len(context.encode()), MAX_CONTEXT_BYTES)


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only chat tests; provider is always mocked")
class AssistantDatabaseTests(TenantDatabaseCase):
    def setUp(self):
        super().setUp()
        apply_ai_read_migration(self.connection)
        self.stack.enter_context(patch.dict(os.environ, {"OPENAI_API_KEY": "provider-test-only", "OPENAI_ALLOWED_MODELS": "fixture-model"}))

    def enable(self, company, daily=50):
        config = {"global_enabled": True, "routine_model": "fixture-model", "document_model": "fixture-model",
                  "input_cost_per_million": "1", "output_cost_per_million": "2", "daily_request_limit": daily}
        with self.factory() as db:
            db.execute(text("update ai_platform_settings set config=cast(:config as jsonb) where id=true"),
                       {"config": json.dumps(config)})
            db.execute(text("update tenant_feature_controls set platform_allowed=true where company_id=:company and feature_key='ai'"),
                       {"company": company})
            db.execute(text("update ai_tenant_settings set tenant_enabled=true where company_id=:company"), {"company": company})
            db.commit()

    def service(self, db, identity):
        db.info["tenant_context"] = identity
        return AssistantService(db, identity)

    def test_first_message_titles_only_a_new_default_conversation(self):
        first, _, _ = self.register("ai-title")
        identity = first["user"]
        self.enable(identity["company_id"])
        with self.factory() as db:
            service = self.service(db, identity)
            default = service.create(ConversationCreate())
            custom = service.create(ConversationCreate(title="My custom title"))
            result = ProviderResult(AssistantOutput(reply="Ready.", clarification=None), 20, 0, 10, "fixture")
            with patch("app.ai.service.OpenAIProvider.respond", return_value=result):
                service.send(default["id"], MessageCreate(content="  Create a purchase\nfor Copper Tumbler  ", client_key=uuid4()))
                self.assertEqual(service.conversation(default["id"])["title"], "Create a purchase for Copper Tumbler")
                service.send(default["id"], MessageCreate(content="Another question", client_key=uuid4()))
                self.assertEqual(service.conversation(default["id"])["title"], "Create a purchase for Copper Tumbler")
                service.send(custom["id"], MessageCreate(content="Create a vendor", client_key=uuid4()))
                self.assertEqual(service.conversation(custom["id"])["title"], "My custom title")

    def test_private_history_preferences_and_composite_ownership(self):
        first, cookies, _ = self.register("ai-history")
        second, _, _ = self.register("ai-other")
        first_identity, second_identity = first["user"], second["user"]
        with self.factory() as db:
            user = db.execute(text("""insert into tenant_users(company_id,email,display_name,password_hash)
                values(:company,:email,'Other user','unused') returning id"""),
                {"company": first_identity["company_id"], "email": f"other-{self.suffix}@example.com"}).scalar_one()
            db.execute(text("insert into tenant_memberships(company_id,user_id,role) values(:company,:user,'staff')"),
                       {"company": first_identity["company_id"], "user": user})
            db.commit()
        with self.factory() as db:
            service = self.service(db, first_identity)
            conversation = service.create(ConversationCreate(title="Private lamps"))
            service.save_preference("language", "Tamil")
            self.assertEqual(service.preferences()["items"][0]["value"], "Tamil")
        for identity in (second_identity, {**first_identity, "user_id": str(user), "role": "staff"}):
            with self.factory() as db:
                service = self.service(db, identity)
                self.assertEqual(service.list_conversations()["items"], [])
                self.assertEqual(service.preferences()["items"], [])
                with self.assertRaises(HTTPException) as error:
                    service.conversation(conversation["id"])
                self.assertEqual(error.exception.status_code, 404)
        self.use_cookies(cookies)
        self.assertEqual(self.client.get(f"/ai/conversations/{conversation['id']}").status_code, 200)
        self.assertEqual(self.client.post("/ai/conversations", json={"title": "x", "user_id": str(user)}, headers=self.headers(cookies)).status_code, 422)
        update = self.client.patch(f"/ai/conversations/{conversation['id']}",
            json={"title": "Renamed lamps", "expected_version": 1}, headers=self.headers(cookies))
        self.assertEqual(update.status_code, 200, update.text)
        self.assertEqual(self.client.patch(f"/ai/conversations/{conversation['id']}",
            json={"status": "archived", "expected_version": 1}, headers=self.headers(cookies)).status_code, 409)

    def test_message_replay_context_usage_and_archive_delete(self):
        first, cookies, _ = self.register("ai-chat")
        identity = first["user"]
        self.enable(identity["company_id"])
        with self.factory() as db:
            service = self.service(db, identity)
            conversation = service.create(ConversationCreate(title="Purchase discussion"))
            service.save_preference("instructions", "Use short explanations")
            payload = MessageCreate(content="I bought 20 lamps.", client_key=uuid4())
            contexts = []
            def respond(context, content, config):
                self.assertFalse(db.in_transaction(), "No DB transaction may span an external call")
                contexts.append(context)
                self.assertEqual(content, payload.content)
                return ProviderResult(AssistantOutput(reply="I cannot post a purchase yet.", clarification="What was the bill total?"), 100, 0, 20, "fixture-reference")
            with patch("app.ai.service.OpenAIProvider.respond", side_effect=respond) as provider:
                result = service.send(conversation["id"], payload)
                self.assertEqual(len(result["items"]), 2)
                self.assertEqual(result["items"][0]["role"], "user")
                replay = service.send(conversation["id"], payload)
                self.assertEqual(len(replay["items"]), 2)
                self.assertEqual(provider.call_count, 1)
            self.assertIn("Use short explanations", contexts[0])
            self.assertLessEqual(len(contexts[0].encode()), MAX_CONTEXT_BYTES)
            self.assertIn('"available_read_capabilities":{}', contexts[0])
            self.assertIn('"available_draft_actions":{}', contexts[0])
            self.assertIn("No SQL/execution tools exist", contexts[0])
            self.assertEqual(service.usage()["personal"]["requests"], 1)
            self.assertEqual(service.usage()["personal"]["tokens"], 120)
            with self.assertRaises(HTTPException) as error:
                service.send(conversation["id"], MessageCreate(content="different", client_key=payload.client_key))
            self.assertEqual(error.exception.status_code, 409)
            current = service.conversation(conversation["id"])
            archived = service.update(conversation["id"], ConversationUpdate(status="archived", expected_version=current["version"]))
            with self.assertRaises(HTTPException):
                service.send(conversation["id"], MessageCreate(content="another", client_key=uuid4()))
            service.delete(conversation["id"], archived["version"])
            self.assertEqual(service.list_conversations(archived=True)["items"], [])
            self.assertEqual(db.execute(text("select content from ai_messages")).scalars().all(), ["", ""])
            self.assertGreater(db.execute(text("select count(*) from ai_audit_events")).scalar_one(), 0)
            self.assertEqual(service.usage()["personal"]["requests"], 1)

    def test_unknown_provider_outcome_keeps_reservation_and_daily_limit_is_exact(self):
        first, _, _ = self.register("ai-quota")
        identity = first["user"]
        self.enable(identity["company_id"], daily=1)
        with self.factory() as db:
            service = self.service(db, identity)
            conversation = service.create(ConversationCreate())
            payload = MessageCreate(content="Help me record a purchase", client_key=uuid4())
            with patch("app.ai.service.OpenAIProvider.respond", return_value=ProviderResult(None, None, None, None, None, "provider_unknown")) as provider:
                result = service.send(conversation["id"], payload)
                self.assertEqual(result["items"][0]["status"], "unknown")
                replay = service.send(conversation["id"], payload)
                self.assertEqual(replay["items"][0]["status"], "unknown")
                self.assertEqual(provider.call_count, 1)
                charged = db.execute(text("select charged_cost,reserved_cost,charged_tokens,reserved_tokens from ai_usage_reservations")).one()
                self.assertEqual(charged.charged_cost, charged.reserved_cost)
                self.assertEqual(charged.charged_tokens, charged.reserved_tokens)
                savepoint = self.connection.begin_nested()
                # A rejected reservation aborts the session transaction, so isolate it from this rollback fixture.
                with patch.object(db, "rollback", side_effect=savepoint.rollback):
                    with self.assertRaises(HTTPException) as error:
                        service.send(conversation["id"], MessageCreate(content="second", client_key=uuid4()))
                self.assertEqual(error.exception.status_code, 429)
                self.assertEqual(provider.call_count, 1)

    def test_feature_disable_and_viewer_role_block_new_provider_calls(self):
        first, cookies, _ = self.register("ai-off")
        identity = first["user"]
        self.enable(identity["company_id"])
        self.use_cookies(cookies)
        conversation = self.client.post("/ai/conversations", json={"title": "Own history"}, headers=self.headers(cookies)).json()
        with self.factory() as db:
            db.execute(text("update tenant_feature_controls set platform_allowed=false where company_id=:company and feature_key='ai'"),
                       {"company": identity["company_id"]})
            db.commit()
        with patch("app.ai.service.OpenAIProvider.respond") as provider:
            result = self.client.post(f"/ai/conversations/{conversation['id']}/messages",
                json={"content": "hello", "client_key": str(uuid4())}, headers=self.headers(cookies))
            self.assertEqual(result.status_code, 403, result.text)
            provider.assert_not_called()
        self.assertEqual(self.client.get("/ai/conversations").status_code, 200)
        with self.factory() as db:
            db.execute(text("update tenant_memberships set role='viewer' where user_id=:user and company_id=:company"),
                       {"user": identity["user_id"], "company": identity["company_id"]})
            db.commit()
        self.assertEqual(self.client.get("/ai/conversations").status_code, 200)
        self.assertEqual(self.client.post("/ai/conversations", json={}, headers=self.headers(cookies)).status_code, 403)

    def test_exact_monthly_token_and_cost_limits_and_identity_bound_reservations(self):
        owner, _, _ = self.register("ai-boundary")
        identity = owner["user"]
        self.enable(identity["company_id"])
        with self.factory() as db:
            db.execute(text("""update ai_platform_settings set config=config||cast(:patch as jsonb)
                where id=true"""), {"patch": json.dumps({"monthly_token_limit": 1100})})
            db.commit()
        with self.factory() as db:
            service = self.service(db, identity)
            conversation = service.create(ConversationCreate())
            def pending_message():
                message = uuid4()
                db.execute(text("""insert into ai_messages(id,company_id,user_id,conversation_id,client_key,role,content,status,deadline)
                    values(:id,:company,:user,:conversation,:key,'user','Bounded request','pending',now()+interval '1 minute')"""),
                    {**service.scope, "id": message, "conversation": conversation["id"], "key": uuid4()})
                return message
            message = pending_message()
            reservation = db.execute(text("select tenali_ai_reserve(:message,'fixture-model',1000,100)"),
                                     {"message": message}).scalar_one()
            self.assertIsNotNone(reservation, "A reservation exactly at the token ceiling must pass")
            second = pending_message()
            savepoint = self.connection.begin_nested()
            with self.assertRaises(DBAPIError) as error:
                db.execute(text("select tenali_ai_reserve(:message,'fixture-model',1,100)"), {"message": second})
            self.assertEqual(error.exception.orig.sqlstate, "P0001")
            savepoint.rollback()
            db.commit()
        other, _, _ = self.register("ai-cost")
        identity = other["user"]
        self.enable(identity["company_id"])
        with self.factory() as db:
            db.execute(text("""update ai_platform_settings set config=config||cast(:patch as jsonb)
                where id=true"""), {"patch": json.dumps({"monthly_token_limit": 1000000, "monthly_cost_limit": 1,
                    "input_cost_per_million": "1000", "output_cost_per_million": "1000"})})
            db.commit()
        with self.factory() as db:
            service = self.service(db, identity)
            conversation = service.create(ConversationCreate())
            message = uuid4()
            db.execute(text("""insert into ai_messages(id,company_id,user_id,conversation_id,client_key,role,content,status)
                values(:id,:company,:user,:conversation,:key,'user','Cost request','pending')"""),
                {**service.scope, "id": message, "conversation": conversation["id"], "key": uuid4()})
            reservation = db.execute(text("select tenali_ai_reserve(:message,'fixture-model',900,100)"), {"message": message}).scalar_one()
            cost = db.execute(text("select reserved_cost from ai_usage_reservations where id=:id"), {"id": reservation}).scalar_one()
            self.assertEqual(cost, Decimal("1.00000000"), "A reservation exactly at the USD ceiling must pass")
            savepoint = self.connection.begin_nested()
            with self.assertRaises(DBAPIError) as error:
                db.execute(text("select tenali_ai_reserve(:message,'fixture-model',1,100)"), {"message": message})
            self.assertEqual(error.exception.orig.sqlstate, "P0001")
            savepoint.rollback()

    def test_disable_between_reservation_and_call_releases_unused_reservation(self):
        owner, _, _ = self.register("ai-recheck")
        identity = owner["user"]
        self.enable(identity["company_id"])
        with self.factory() as db:
            service = self.service(db, identity)
            conversation = service.create(ConversationCreate())
            with patch.object(service, "recheck_before_provider", return_value=None), patch("app.ai.service.OpenAIProvider.respond") as provider:
                result = service.send(conversation["id"], MessageCreate(content="hello", client_key=uuid4()))
            provider.assert_not_called()
            self.assertEqual(result["items"][0]["status"], "failed")
            self.assertEqual(service.usage()["personal"]["tokens"], 0)


if __name__ == "__main__":
    unittest.main()
