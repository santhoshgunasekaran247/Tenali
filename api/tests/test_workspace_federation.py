import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import text

from app.services.federation_settings import FederationSettings
from app.services.tenant_security import password_hash
from test_tenancy import TenantDatabaseCase

SETTINGS = {"supabase_url": "https://abcdefghijklmnopqrst.supabase.co", "public_key": "sb_publishable_public_fixture_key",
            "providers": ["google", "custom:yahoo", "facebook"], "enabled": True}


class FederationSettingsTests(unittest.TestCase):
    def test_settings_reject_unsafe_domains_providers_and_missing_values(self):
        FederationSettings(**SETTINGS)
        for changes in [{"supabase_url": "https://example.com"}, {"supabase_url": "http://127.0.0.1"},
                        {"providers": ["phone"]}, {"providers": []}, {"providers": ["google", "google"]},
                        {"supabase_url": ""}, {"public_key": ""}, {"public_key": "sb_secret_never_expose"},
                        {"supabase_url": "https://abcdefghijklmnopqrst.supabase.co/other"}]:
            with self.assertRaises(ValidationError):
                FederationSettings(**{**SETTINGS, **changes})


class WorkspaceFederationTests(TenantDatabaseCase):
    def social_create(self, slug, social=None, headers=None):
        social = social or {"uid": "workspace-social-fixture", "email": "owner-social@example.com", "name": "Social Owner"}
        with patch("app.api.routes.auth.verified_identity", return_value=social):
            return self.client.post("/auth/register-social",
                json={"company_name": "Social Workspace", "slug": slug, "id_token": "signed-fixture"},
                headers=headers or {"Origin": "http://localhost"})

    def test_social_creation_and_owner_login_preserve_tenant_boundaries(self):
        first = self.social_create("social-a-" + self.suffix)
        self.assertEqual(first.status_code, 201, first.text)
        user = first.json()["user"]
        self.assertEqual(user["email"], "owner-social@example.com")
        with self.factory() as db:
            owner = db.execute(text("select password_hash,supabase_uid from tenant_users where id=:id"), {"id": user["user_id"]}).mappings().one()
            self.assertIsNone(owner["password_hash"])
            self.assertEqual(owner["supabase_uid"], "workspace-social-fixture")
            self.assertEqual(db.execute(text("select count(*) from stores where company_id=:company and is_default"), {"company": user["company_id"]}).scalar_one(), 1)
        self.client.cookies.clear()
        headers = {"Origin": "http://localhost", "X-Tenant-Slug": user["tenant_slug"]}
        with patch("app.api.routes.auth.verified_identity", return_value={"uid": "workspace-social-fixture", "email": user["email"], "name": "Owner"}):
            login = self.client.post("/auth/login-social", json={"id_token": "fixture"}, headers=headers)
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(login.json()["user"]["user_id"], user["user_id"])
        password = self.client.post("/auth/login", json={"email": user["email"], "password": "anything"}, headers=headers)
        self.assertEqual(password.status_code, 401, password.text)
        with patch("app.api.routes.auth.verified_identity", return_value={"uid": "wrong-identity", "email": user["email"], "name": "Claimant"}):
            denied = self.client.post("/auth/login-social", json={"id_token": "fixture"}, headers=headers)
        self.assertEqual(denied.status_code, 403, denied.text)
        self.client.cookies.clear()
        second = self.social_create("social-b-" + self.suffix)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertNotEqual(user["user_id"], second.json()["user"]["user_id"])
        denied_creation = self.social_create("social-c-" + self.suffix, headers=headers)
        self.assertEqual(denied_creation.status_code, 403, denied_creation.text)
        injected = self.client.post("/auth/register-social", json={"company_name": "Injected", "slug": "inject-" + self.suffix,
            "id_token": "fixture", "email": "other@example.com"}, headers={"Origin": "http://localhost"})
        self.assertEqual(injected.status_code, 422, injected.text)
        random = self.client.post("/auth/register", json={"company_name": "Random", "slug": "random-" + self.suffix,
            "email": "random@example.com", "display_name": "Random", "password": "Random long password 123!"},
            headers={"Origin": "http://localhost"})
        self.assertEqual(random.status_code, 410, random.text)

    def test_platform_settings_are_admin_only_shared_and_project_locked(self):
        legacy, cookies, email = self.register("legacy-settings")
        self.assertEqual(self.client.get("/platform/social-login").status_code, 401)
        self.assertEqual(self.client.put("/platform/social-login", json=SETTINGS, headers=self.headers(cookies)).status_code, 403)
        admin_email = uuid4().hex + "@example.com"
        with self.factory() as db:
            db.execute(text("insert into platform_admins(email,display_name,password_hash) values(:email,'Operator',:hash)"),
                       {"email": admin_email, "hash": password_hash("Operator fixture password 123!")})
            db.commit()
        self.client.cookies.clear()
        logged = self.client.post("/platform/login", json={"email": admin_email, "password": "Operator fixture password 123!"}, headers={"Origin": "http://localhost"})
        self.assertEqual(logged.status_code, 200, logged.text)
        headers = {"Origin": "http://localhost", "X-CSRF-Token": self.client.cookies["tenali_platform_csrf"]}
        missing_csrf = self.client.put("/platform/social-login", json=SETTINGS)
        self.assertEqual(missing_csrf.status_code, 403, missing_csrf.text)
        saved = self.client.put("/platform/social-login", json=SETTINGS, headers=headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get("/auth/social-config").json()["supabase"]["url"], SETTINGS["supabase_url"])
        shopper = self.client.get("/shop/auth-config", headers={"X-Tenant-Slug": legacy["user"]["tenant_slug"]})
        self.assertEqual(shopper.json(), self.client.get("/auth/social-config").json())
        self.social_create("lock-project-" + self.suffix)
        changed = self.client.put("/platform/social-login", json={**SETTINGS, "supabase_url": "https://zyxwvutsrqponmlkjihg.supabase.co"}, headers=headers)
        self.assertEqual(changed.status_code, 409, changed.text)
        disabled = self.client.put("/platform/social-login", json={**SETTINGS, "enabled": False}, headers=headers)
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(self.client.get("/auth/social-config").json()["enabled"])
        self.client.cookies.clear()
        staff_login = self.client.post("/auth/login", json={"email": email, "password": "Test password for tenancy 123!"},
            headers={"Origin": "http://localhost", "X-Tenant-Slug": legacy["user"]["tenant_slug"]})
        self.assertEqual(staff_login.status_code, 200, staff_login.text)
