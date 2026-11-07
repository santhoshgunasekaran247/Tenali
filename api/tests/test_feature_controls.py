import os
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services.feature_controls import (
    AIConfig, AIOverrides, FeatureUpdate, TenantAIUpdate,
    company_features, save_feature, validate_limits,
)
from app.services.tenant_security import password_hash, token_digest
from test_storefront_toggle import StorefrontToggleTests
from test_tenancy import TenantDatabaseCase


class FeatureConfigTests(unittest.TestCase):
    def test_defaults_keep_ai_off_and_limits_bounded(self):
        self.assertFalse(AIConfig().global_enabled)
        for values in ({"daily_request_limit": 0}, {"monthly_token_limit": -1},
                       {"timeout_seconds": 121}, {"global_enabled": True},
                       {"support_url": "javascript:alert(1)"}, {"support_url": "http://example.com"},
                       {"support_url": "https://user:secret@example.com"}, {"routine_model": "https://example.com"},
                       {"api_key": "not-accepted"}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                AIConfig(**values)

    def test_contact_and_model_values(self):
        for contact in ("", "https://support.example.com/help", "mailto:support@example.com"):
            self.assertEqual(AIConfig(support_url=contact).support_url, contact)
        self.assertTrue(AIConfig(global_enabled=True, routine_model="candidate-model", document_model="candidate-model").global_enabled)

    def test_null_overrides_inherit_and_cannot_raise_ceilings(self):
        defaults = AIConfig().model_dump()
        self.assertEqual(validate_limits({}, defaults)["daily_request_limit"], 50)
        self.assertEqual(validate_limits({"daily_request_limit": 2}, defaults)["daily_request_limit"], 2)
        with self.assertRaises(HTTPException) as error:
            validate_limits({"daily_request_limit": 51}, defaults)
        self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(ValidationError):
            AIOverrides(monthly_cost_limit=0)

    def test_identity_and_platform_claims_rejected_in_tenant_payload(self):
        with self.assertRaises(ValidationError):
            TenantAIUpdate(tenant_enabled=True, expected_version=1, platform_allowed=True)

    def test_effective_feature_truth_table_and_global_ai_kill_switch(self):
        for allowed in (False, True):
            for enabled in (False, True):
                for global_enabled in (False, True):
                    with self.subTest(allowed=allowed, enabled=enabled, global_enabled=global_enabled):
                        company, controls, preference, settings = (Mock() for _ in range(4))
                        company.mappings.return_value.first.return_value = {"is_active": True, "storefront_enabled": enabled}
                        controls.mappings.return_value.all.return_value = [
                            {"feature_key": key, "platform_allowed": allowed, "version": 1}
                            for key in ("ai", "storefront")
                        ]
                        preference.mappings.return_value.first.return_value = {"tenant_enabled": enabled, "version": 1}
                        settings.mappings.return_value.first.return_value = {"config": {
                            "global_enabled": global_enabled, "routine_model": "candidate", "document_model": "candidate",
                        }, "version": 1}
                        db = Mock()
                        db.execute.side_effect = [company, controls, preference, settings]
                        result = company_features(db, uuid4())
                        self.assertEqual(result["storefront"]["effective_enabled"], allowed and enabled)
                        self.assertEqual(result["ai"]["tenant_enabled"], enabled)
                        self.assertFalse(result["ai"]["effective_enabled"], "AI runtime is not available in Phase 1A")
                        if allowed and not global_enabled:
                            self.assertEqual(result["ai"]["reason"], "platform_ai_disabled")


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only configuration tests")
class FeatureControlDatabaseTests(TenantDatabaseCase):
    save_company = StorefrontToggleTests.save_company

    def platform_session(self):
        admin = uuid4()
        token = uuid4().hex
        with self.factory() as db:
            db.execute(text("""insert into platform_admins(id,email,display_name,password_hash)
                values(:id,:email,'AI fixture',:hash)"""),
                {"id": admin, "email": f"ai-{self.suffix}@example.com", "hash": password_hash("Platform test password 123!")})
            db.execute(text("""insert into platform_sessions(token_hash,admin_id,expires_at)
                values(:token,:admin,now()+interval '1 hour')"""), {"token": token_digest(token), "admin": admin})
            db.commit()
        return admin, {"tenali_platform": token, "tenali_platform_csrf": "ai-fixture"}

    def test_platform_storefront_disable_preserves_tenant_preference_and_operations(self):
        owner, cookies, _ = self.register("feature-shop")
        company = owner["user"]["company_id"]
        admin, _ = self.platform_session()
        with self.factory() as db:
            status = company_features(db, company)
            self.assertTrue(status["storefront"]["effective_enabled"])
            self.assertFalse(status["ai"]["platform_allowed"])
            disabled = save_feature(db, company, FeatureUpdate(feature_key="storefront", platform_allowed=False,
                                                              expected_version=status["storefront"]["version"]), admin)
            self.assertTrue(disabled["storefront"]["tenant_enabled"])
            self.assertFalse(disabled["storefront"]["effective_enabled"])
        self.use_cookies(cookies)
        profile = self.client.get("/company")
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertTrue(profile.json()["storefront_enabled"])
        self.assertEqual(self.save_company(cookies, company_name="Still operating").status_code, 200)
        self.assertEqual(self.client.get("/ai/settings").status_code, 200)
        self.assertEqual(self.save_company(cookies, storefront_enabled=False).status_code, 200)
        rejected = self.save_company(cookies, storefront_enabled=True)
        self.assertEqual(rejected.status_code, 403, rejected.text)
        self.client.cookies.clear()
        public = {"X-Tenant-Slug": owner["user"]["tenant_slug"]}
        self.assertFalse(self.client.get("/catalog/company", headers=public).json()["storefront_enabled"])
        for path in ("/catalog/home", "/catalog/list", "/shop/availability"):
            self.assertEqual(self.client.get(path, headers=public).status_code, 403, path)
        self.assertEqual(self.client.get("/shop/auth-config", headers=public).status_code, 200)
        with self.factory() as db:
            enabled = save_feature(db, company, FeatureUpdate(feature_key="storefront", platform_allowed=True,
                                                            expected_version=disabled["storefront"]["version"]), admin)
            self.assertFalse(enabled["storefront"]["effective_enabled"], "Platform allow must not overwrite tenant opt-out")

    def test_platform_and_tenant_settings_roles_versions_and_secret_redaction(self):
        owner, cookies, _ = self.register("feature-ai")
        company = owner["user"]["company_id"]
        admin, platform_cookies = self.platform_session()
        self.use_cookies(cookies)
        denied = self.client.get("/platform/ai/settings")
        self.assertEqual(denied.status_code, 403)
        result = self.client.patch("/ai/settings", json={"tenant_enabled": True, "expected_version": 1}, headers=self.headers(cookies))
        self.assertEqual(result.status_code, 403)
        self.use_cookies(platform_cookies)
        headers = {"Origin": "http://localhost", "X-CSRF-Token": platform_cookies["tenali_platform_csrf"]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "redaction-fixture"}):
            response = self.client.get("/platform/ai/settings")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("redaction-fixture", response.text)
        config = response.json()
        self.assertTrue(config["provider_configured"])
        for key in ("version", "runtime_ready", "provider_configured", "model_ready"):
            config.pop(key)
        config.update(global_enabled=True, routine_model="candidate-model", document_model="candidate-model", expected_version=1)
        saved = self.client.put("/platform/ai/settings", json=config, headers=headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.put("/platform/ai/settings", json=config, headers=headers).status_code, 409)
        allowed = self.client.patch(f"/platform/workspaces/{company}/features",
            json={"feature_key": "ai", "platform_allowed": True, "expected_version": 1}, headers=headers)
        self.assertEqual(allowed.status_code, 200, allowed.text)
        limits_path = f"/platform/ai/tenants/{company}"
        self.assertEqual(self.client.patch(limits_path, json={"daily_request_limit": 51, "expected_version": 1}, headers=headers).status_code, 422)
        lower = self.client.patch(limits_path, json={"daily_request_limit": 2, "expected_version": 1}, headers=headers)
        self.assertEqual(lower.status_code, 200, lower.text)
        reset = self.client.patch(limits_path, json={"daily_request_limit": None, "expected_version": 2}, headers=headers)
        self.assertEqual(reset.json()["effective"]["daily_request_limit"], 50)
        self.use_cookies(cookies)
        result = self.client.patch("/ai/settings", json={"tenant_enabled": True, "expected_version": 1}, headers=self.headers(cookies))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["ai"]["tenant_enabled"])
        self.assertFalse(result.json()["ai"]["effective_enabled"], "Phase 1A must not claim a working assistant")
        stale = self.client.patch("/ai/settings", json={"tenant_enabled": False, "expected_version": 1}, headers=self.headers(cookies))
        self.assertEqual(stale.status_code, 409)
        with self.factory() as db:
            db.execute(text("update tenant_memberships set role='staff' where user_id=:user and company_id=:company"),
                       {"user": owner["user"]["user_id"], "company": company})
            db.commit()
        self.assertEqual(self.client.get("/ai/settings").status_code, 200)
        self.assertEqual(self.client.patch("/ai/settings", json={"tenant_enabled": False, "expected_version": 2}, headers=self.headers(cookies)).status_code, 403)
        with self.factory() as db:
            actions = db.execute(text("select action from platform_audit where admin_id=:admin"), {"admin": admin}).scalars().all()
        self.assertIn("AI_PLATFORM_SETTINGS_UPDATED", actions)
        self.assertIn("AI_PLATFORM_ENABLED", actions)

    def test_database_scope_and_platform_write_grants(self):
        first, _, _ = self.register("scope-ai-a")
        second, _, _ = self.register("scope-ai-b")
        with self.factory() as db:
            db.info["tenant_context"] = first["user"]
            rows = db.execute(text("select company_id from tenant_feature_controls")).scalars().all()
            self.assertEqual({str(value) for value in rows}, {first["user"]["company_id"]})
            self.assertFalse(db.execute(text("select * from ai_tenant_settings where company_id=:company"),
                                        {"company": second["user"]["company_id"]}).first())
            savepoint = self.connection.begin_nested()
            with self.assertRaises(DBAPIError):
                db.execute(text("update tenant_feature_controls set platform_allowed=true"))
            savepoint.rollback()
        with self.factory() as db:
            db.execute(text("update tenant_memberships set role='staff' where user_id=:user and company_id=:company"),
                       {"user": first["user"]["user_id"], "company": first["user"]["company_id"]})
            db.commit()
        with self.factory() as db:
            db.info["tenant_context"] = first["user"]
            changed = db.execute(text("update ai_tenant_settings set tenant_enabled=true returning id")).all()
            self.assertEqual(changed, [], "Staff must not change preferences even through tenant runtime SQL")


if __name__ == "__main__":
    unittest.main()
