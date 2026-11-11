import json
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.ai.actions import ACTIONS, ActionAssistantOutput, DraftApproval, DraftCreate, DraftEdit, DraftProposal
from app.ai.drafts import DraftService, action_policies, available_actions, bounded_payload, digest, reject_extra_fields
from app.ai.provider import OpenAIProvider, ProviderResult
from app.ai.schemas import AssistantOutput, ConversationCreate, MessageCreate
from app.ai.service import AssistantService
from schema_support import apply_ai_business_read_migration
from test_tenancy import TenantDatabaseCase
from test_ai_reads import ReadDatabaseTests


class DraftUnitTests(unittest.TestCase):
    def test_operational_allowlist_separates_high_impact_and_excludes_admin(self):
        self.assertEqual(len(ACTIONS), 42)
        self.assertEqual({key for key, action in ACTIONS.items() if action.high_impact},
                         {"invoice_cancel", "purchase_cancel", "product_delete", "transaction_delete",
                          "account_transaction_reverse", "stock_transfer_reverse", "product_merge", "receivable_status"})
        self.assertTrue({"party_create", "party_update", "product_create", "product_update"} <= set(ACTIONS))
        for action in ("delete", "company_update", "period_reopen", "workspace_reset"):
            with self.assertRaises(ValidationError):
                DraftProposal(action=action, target_id=None, payload_json="{}")
        with self.assertRaises(ValidationError):
            DraftCreate(action="party_create", payload={}, client_key=uuid4(), user_id=uuid4())

    def test_payload_bounds_unknown_nested_fields_and_submission_injection(self):
        for key in ("company_id", "user_id", "idempotency_key", "attachments"):
            with self.assertRaises(HTTPException):
                bounded_payload({key: "injected"})
        with self.assertRaises(HTTPException):
            bounded_payload({"notes": "\u0915" * 9000})
        with self.assertRaises(HTTPException):
            bounded_payload({"amount": float("nan")})
        nested = {}
        for _ in range(10):
            nested = {"value": nested}
        with self.assertRaises(HTTPException):
            bounded_payload(nested)
        with self.assertRaises(HTTPException):
            reject_extra_fields(ACTIONS["purchase_create"].schema, {"lines": [{"company_id": "bad"}]})
        self.assertEqual(digest({"amount": "1", "notes": "ok"}), digest({"notes": "ok", "amount": "1"}))
        self.assertNotEqual(digest({"amount": "1"}), digest({"amount": "2"}))

    def test_draft_schema_keeps_required_explicit_nulls_and_positive_money(self):
        for amount in ("0", "-1", "NaN", "Infinity"):
            with self.assertRaises(ValidationError):
                ACTIONS["collection_payment"].schema.model_validate(
                    {"amount": amount, "account_id": uuid4(), "payment_mode": "Cash", "idempotency_key": "fixture-key"})
        with self.assertRaises(ValidationError):
            ActionAssistantOutput.model_validate({"reply": "Hello", "clarification": None, "lookups": []})
        with self.assertRaises(ValidationError):
            DraftApproval(expected_version=1, expected_hash="not-a-hash")

    def test_provider_proposes_only_a_draft_and_preserves_metering_without_tools(self):
        output = {"reply": "Please review this private draft.", "clarification": None, "lookups": [],
                  "draft": {"action": "party_create", "target_id": None,
                            "payload_json": json.dumps({"party_type": "customer", "legal_name": "Example"})}}
        response = SimpleNamespace(status="completed", id="mock-draft", output_text=json.dumps(output),
            usage=SimpleNamespace(input_tokens=50, output_tokens=25, input_tokens_details=SimpleNamespace(cached_tokens=0)))
        with patch("app.ai.provider.OpenAI") as client:
            client.return_value.__enter__.return_value.responses.create.return_value = response
            result = OpenAIProvider().respond("context", "draft a customer", {
                "timeout_seconds": 30, "routine_model": "fixture-model", "max_output_tokens": 200,
                "_draft_actions": [{"key": "party_create"}]})
            options = client.return_value.__enter__.return_value.responses.create.call_args.kwargs
        self.assertEqual(result.draft.action, "party_create")
        self.assertEqual(result.input_tokens, 50)
        self.assertFalse(options["store"])
        self.assertNotIn("tools", options)
        self.assertEqual(options["text"]["format"]["schema"]["additionalProperties"], False)

    def test_store_limited_and_module_restricted_actions_are_not_offered(self):
        items = [{"key": key, "enabled": True, "compatible": True, "tenant_allowed": True} for key in ACTIONS]
        with patch("app.ai.drafts.action_policies", return_value={"items": items}):
            offered = available_actions(Mock(), {"company_id": uuid4(), "role": "staff", "modules": ["parties"], "store_ids": []})
        self.assertEqual({item["key"] for item in offered}, {"party_create", "party_update"})

    def test_party_drafts_reject_empty_null_and_invalid_required_values(self):
        assistant = Mock()
        assistant.scope = {"company": "fixture", "user": "fixture"}
        service = DraftService(assistant)
        with patch.object(service, "gate", return_value=({}, {})), \
             patch.object(service, "reference", return_value={"party_type": "customer"}), \
             patch("app.ai.drafts.managed_schema", return_value=True):
            for payload in ({"party_type": ""}, {"party_type": None}, {"party_type": "invalid"},
                            {"is_active": None}, {"legal_name": None}):
                with self.assertRaises(HTTPException) as error:
                    service.preflight({"id": uuid4(), "action_key": "party_update", "target_id": uuid4(), "payload": payload})
                self.assertEqual(error.exception.status_code, 422)

    def test_isolated_guard_runs_before_fixture_schema_changes(self):
        actual = MagicMock()
        actual.connect.return_value.__enter__.return_value.execute.return_value.scalar_one.return_value = "not-isolated"
        case = DraftDatabaseTests("test_same_tenant_users_and_expired_drafts_are_private")
        with patch.dict(os.environ, {"TENALI_AI_ISOLATED_DB": "tenali_ai_draft_test_fixture"}), \
             patch("app.core.database.engine", actual), patch.object(TenantDatabaseCase, "setUp") as setup:
            with self.assertRaises(RuntimeError):
                case.setUp()
            setup.assert_not_called()

    def test_missing_tenant_is_explicit_and_undeployed_contract_fails_closed(self):
        db = Mock()
        db.execute.return_value.first.return_value = None
        with self.assertRaises(HTTPException) as error:
            action_policies(db, uuid4())
        self.assertEqual(error.exception.status_code, 404)
        db.execute.return_value.mappings.return_value = [{"key": "future_action", "fingerprint": "", "enabled": True, "execution_enabled": False}]
        policy = action_policies(db)["items"][0]
        self.assertFalse(policy["compatible"])
        self.assertFalse(policy["execution_enabled"])
        self.assertEqual(policy["description"], "Adapter not deployed")


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Synthetic isolated draft DB required; provider always mocked")
class DraftDatabaseTests(TenantDatabaseCase):
    def setUp(self):
        expected = os.getenv("TENALI_AI_ISOLATED_DB", "")
        if not expected.startswith(("tenali_ai_draft_test_", "tenali_ai_write_test_")):
            raise RuntimeError("Draft tests refuse a non-isolated database.")
        from app.core.database import engine
        with engine.connect() as probe:
            if probe.execute(text("select current_database()")).scalar_one() != expected:
                raise RuntimeError("Draft tests refuse a non-isolated database.")
        super().setUp()
        self.assertEqual(self.connection.execute(text("select current_database()")).scalar_one(), expected)
        apply_ai_business_read_migration(self.connection)
        self.stack.enter_context(patch.dict(os.environ, {"OPENAI_API_KEY": "mock-only", "OPENAI_ALLOWED_MODELS": "fixture-model"}))
        self.owner, self.cookies, _ = self.register("ai-draft")
        self.identity = self.owner["user"]
        ReadDatabaseTests.enable(self, self.identity, ())
        with self.factory() as db:
            self.assertEqual(db.execute(text("select count(*) from ai_action_controls where enabled or fingerprint<>''")).scalar_one(), 0)
            self.assertEqual(db.execute(text("select count(*) from ai_tenant_action_controls")).scalar_one(), 0)
            db.execute(text("""update ai_action_controls a set enabled=true,fingerprint=r.hash
                from jsonb_to_recordset(cast(:contracts as jsonb)) as r(key text,hash text) where a.key=r.key"""),
                {"contracts": json.dumps([{"key": key, "hash": action.fingerprint} for key, action in ACTIONS.items()])})
            db.execute(text("""insert into ai_tenant_action_controls(company_id,action_key,allowed)
                select :company,key,true from ai_action_controls"""), {"company": self.identity["company_id"]})
            db.commit()

    def service(self, db):
        db.info["tenant_context"] = self.identity
        return AssistantService(db, self.identity)

    def create(self, assistant, **overrides):
        conversation = assistant.create(ConversationCreate())
        draft = DraftService(assistant).create(conversation["id"], DraftCreate(
            **{"action": "party_create", "payload": {"party_type": "customer", "legal_name": "Draft only"}, "client_key": uuid4(), **overrides}))
        return conversation, draft

    def test_versioned_edit_validation_approval_and_idempotent_retry_do_not_write_business(self):
        with self.factory() as db:
            assistant = self.service(db)
            count = db.execute(text("select count(*) from parties")).scalar_one()
            drafts = DraftService(assistant)
            conversation = assistant.create(ConversationCreate())
            request = DraftCreate(action="party_create", payload={"party_type": "customer", "legal_name": "Draft only"}, client_key=uuid4())
            created = drafts.create(conversation["id"], request)
            valid = drafts.validate(created["id"], created["version"])
            self.assertEqual(valid["payload"]["party_type"], "customer")
            approved = drafts.approve(valid["id"], DraftApproval(expected_version=valid["version"], expected_hash=valid["payload_hash"]))
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(approved["approved_version"], approved["version"])
            drafts.approve(valid["id"], DraftApproval(expected_version=valid["version"], expected_hash=valid["payload_hash"]))
            self.assertEqual(db.execute(text("select count(*) from ai_draft_approvals where draft_id=:id"),
                {"id": created["id"]}).scalar_one(), 1)
            self.assertFalse(db.execute(text("select has_table_privilege('tenali_runtime','ai_draft_approvals','UPDATE')")).scalar_one())
            self.assertFalse(db.execute(text("select has_table_privilege('tenali_runtime','ai_draft_approvals','DELETE')")).scalar_one())
            self.assertEqual(drafts.create(conversation["id"], request)["id"], created["id"])
            with self.assertRaises(HTTPException):
                drafts.create(conversation["id"], request.model_copy(update={"payload": {"legal_name": "Different"}}))
            edited = drafts.edit(created["id"], DraftEdit(expected_version=approved["version"], payload={"party_type": "CUSTOMER", "legal_name": "New draft name"}))
            self.assertEqual(edited["status"], "editing")
            self.assertIsNone(edited["approved_version"])
            proof = db.execute(text("select draft_version,payload_hash from ai_draft_approvals where draft_id=:id"),
                {"id": created["id"]}).mappings().one()
            self.assertEqual(proof["draft_version"], approved["version"])
            self.assertEqual(proof["payload_hash"], approved["payload_hash"])
            with self.assertRaises(HTTPException) as stale:
                drafts.approve(valid["id"], DraftApproval(expected_version=valid["version"], expected_hash=valid["payload_hash"]))
            self.assertEqual(stale.exception.status_code, 409)
            self.assertEqual(db.execute(text("select count(*) from parties")).scalar_one(), count)
            drafts.discard(edited["id"], edited["version"])
            self.assertEqual(db.execute(text("select count(*) from ai_draft_approvals where draft_id=:id"),
                {"id": created["id"]}).scalar_one(), 1)

    def test_private_ownership_cross_tenant_target_and_deleted_content(self):
        other, _, _ = self.register("ai-draft-other")
        with self.factory() as db:
            target = db.execute(text("""insert into parties(company_id,party_type,legal_name)
                values(:company,'customer','Foreign') returning id"""), {"company": other["user"]["company_id"]}).scalar_one()
            db.commit()
        with self.factory() as db:
            assistant = self.service(db)
            conversation, created = self.create(assistant)
            with self.assertRaises(HTTPException):
                DraftService(assistant).create(conversation["id"], DraftCreate(
                    action="party_update", target_id=target, payload={"legal_name": "No"}, client_key=uuid4()))
            assistant.delete(conversation["id"], conversation["version"])
            self.assertEqual(db.execute(text("select payload from ai_action_drafts where id=:id"), {"id": created["id"]}).scalar_one(), {})
        with self.factory() as db:
            db.info["tenant_context"] = other["user"]
            self.assertEqual(db.execute(text("select count(*) from ai_action_drafts")).scalar_one(), 0)
            with self.assertRaises(HTTPException):
                DraftService(AssistantService(db, other["user"])).get(created["id"])

    def test_target_change_requires_new_validation_and_approval(self):
        with self.factory() as db:
            target = db.execute(text("""insert into parties(company_id,party_type,legal_name)
                values(:company,'customer','Original') returning id"""), {"company": self.identity["company_id"]}).scalar_one()
            db.commit()
        with self.factory() as db:
            assistant = self.service(db)
            _, created = self.create(assistant, action="party_update", target_id=target, payload={"nickname": "Requested"})
            drafts = DraftService(assistant)
            valid = drafts.validate(created["id"], created["version"])
        with self.factory() as db:
            db.execute(text("update parties set legal_name='Changed' where id=:id"), {"id": target})
            db.commit()
        with self.factory() as db:
            drafts = DraftService(self.service(db))
            with self.assertRaises(HTTPException) as error:
                drafts.approve(valid["id"], DraftApproval(expected_version=valid["version"], expected_hash=valid["payload_hash"]))
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(drafts.get(valid["id"])["status"], "editing")

    def test_chat_draft_retry_is_metered_once_and_chat_yes_is_not_approval(self):
        with self.factory() as db:
            assistant = self.service(db)
            conversation = assistant.create(ConversationCreate())
            request = MessageCreate(content="Draft a customer named Example", client_key=uuid4())
            proposal = DraftProposal(action="party_create", target_id=None,
                payload_json=json.dumps({"party_type": "CUSTOMER", "legal_name": "Example"}))
            result = ProviderResult(AssistantOutput(reply="Review the draft.", clarification=None), 50, 0, 25, "mock-only", draft=proposal)
            with patch("app.ai.service.OpenAIProvider.respond", return_value=result) as provider:
                sent = assistant.send(conversation["id"], request)
                self.assertEqual(sent["items"][0]["status"], "completed")
                assistant.send(conversation["id"], request)
                self.assertEqual(provider.call_count, 1)
            drafts = DraftService(assistant).list(conversation["id"])["items"]
            self.assertEqual(len(drafts), 1)
            self.assertEqual(drafts[0]["status"], "editing")
            with patch("app.ai.service.OpenAIProvider.respond", return_value=replace(result, draft=None)):
                assistant.send(conversation["id"], MessageCreate(content="yes", client_key=uuid4()))
            self.assertEqual(DraftService(assistant).get(drafts[0]["id"])["status"], "editing")
            self.assertEqual(assistant.usage()["personal"]["requests"], 2)
            self.assertEqual(assistant.usage()["personal"]["tokens"], 150)

    def test_policy_revocation_after_provider_denies_draft_but_keeps_usage(self):
        with self.factory() as db:
            assistant = self.service(db)
            conversation = assistant.create(ConversationCreate())
            def respond(*_args):
                with self.factory() as admin:
                    admin.execute(text("update ai_action_controls set enabled=false,version=version+1 where key='party_create'"))
                    admin.commit()
                return ProviderResult(AssistantOutput(reply="Draft proposed.", clarification=None), 50, 0, 25, "mock-only",
                    draft=DraftProposal(action="party_create", target_id=None, payload_json='{"legal_name":"Example"}'))
            with patch("app.ai.service.OpenAIProvider.respond", side_effect=respond):
                result = assistant.send(conversation["id"], MessageCreate(content="Draft Example", client_key=uuid4()))
            self.assertEqual(result["items"][0]["error_code"], "draft_rejected")
            self.assertEqual(DraftService(assistant).list(conversation["id"])["items"], [])
            self.assertEqual(assistant.usage()["personal"]["tokens"], 75)

    def test_http_approval_requires_csrf_exact_version_hash_and_schema_review(self):
        with self.factory() as db:
            assistant = self.service(db)
            _, draft = self.create(assistant)
        headers = self.headers(self.cookies)
        denied = self.client.post(f"/ai/drafts/{draft['id']}/approve", json={
            "expected_version": draft["version"], "expected_hash": draft["payload_hash"]})
        self.assertEqual(denied.status_code, 403, denied.text)
        response = self.client.post(f"/ai/drafts/{draft['id']}/approve", json={
            "expected_version": draft["version"], "expected_hash": draft["payload_hash"]}, headers=headers)
        self.assertEqual(response.status_code, 409, response.text)
        validate = self.client.post(f"/ai/drafts/{draft['id']}/validate?expected_version={draft['version']}", headers=headers)
        self.assertEqual(validate.status_code, 200, validate.text)
        valid = validate.json()
        approved = self.client.post(f"/ai/drafts/{draft['id']}/approve", json={
            "expected_version": valid["version"], "expected_hash": valid["payload_hash"]}, headers=headers)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(self.client.post(f"/ai/drafts/{draft['id']}/execute", headers=headers, json={
            "expected_version": valid["version"], "expected_hash": valid["payload_hash"]}).status_code, 403)

    def test_same_tenant_users_and_expired_drafts_are_private(self):
        with self.factory() as db:
            second_user = db.execute(text("""insert into tenant_users(company_id,email,display_name,password_hash)
                values(:company,:email,'Other fixture user','unused') returning id"""),
                {"company": self.identity["company_id"], "email": f"other-draft-{self.suffix}@example.com"}).scalar_one()
            db.commit()
        with self.factory() as db:
            assistant = self.service(db)
            conversation, draft = self.create(assistant)
        other = {**self.identity, "user_id": str(second_user), "role": "staff"}
        with self.factory() as db:
            db.info["tenant_context"] = other
            self.assertEqual(db.execute(text("select count(*) from ai_action_drafts")).scalar_one(), 0)
            with self.assertRaises(HTTPException):
                DraftService(AssistantService(db, other)).get(draft["id"])
        with self.factory() as db:
            db.execute(text("update ai_action_drafts set expires_at=now()-interval '1 minute' where id=:id"), {"id": draft["id"]})
            db.commit()
        with self.factory() as db:
            drafts = DraftService(self.service(db))
            self.assertEqual(drafts.list(conversation["id"])["items"], [])
            with self.assertRaises(HTTPException):
                drafts.approve(draft["id"], DraftApproval(expected_version=draft["version"], expected_hash=draft["payload_hash"]))


if __name__ == "__main__":
    unittest.main()
