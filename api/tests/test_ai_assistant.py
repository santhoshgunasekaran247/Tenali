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
from sqlalchemy.exc import DBAPIError

from app.ai.provider import OpenAIProvider, ProviderResult, estimated_cost
from app.ai.schemas import AssistantOutput, ConversationCreate, ConversationUpdate, MessageCreate
from app.ai.service import AssistantService, MAX_CONTEXT_BYTES
from schema_support import apply_ai_read_migration
from test_tenancy import TenantDatabaseCase


class AssistantUnitTests(unittest.TestCase):
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
        self.assertNotIn("Oldest question", context)


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
            self.assertIn('"available_read_capabilities": []', contexts[0])
            self.assertIn('"available_draft_actions": []', contexts[0])
            self.assertIn("No SQL or business execution tools exist", contexts[0])
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
