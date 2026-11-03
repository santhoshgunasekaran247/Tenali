import re
import runpy
import unittest
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import inspect, text

from app.schemas.policies import PolicyContent
from app.services.policies import publication_issues
from app.services.policy_templates import PLATFORM_KINDS, TENANT_KINDS, template
from app.services.tenant_security import token_digest
from test_tenancy import TenantDatabaseCase


class PolicyTemplateTests(unittest.TestCase):
    def test_platform_and_tenant_templates_and_publication_requirements(self):
        for kind in PLATFORM_KINDS:
            content = PolicyContent(**template(kind))
            self.assertEqual(content.business_name, "Sru Global (Tenali)")
            self.assertEqual(content.contact_email, "sourcedbysru@gmail.com")
            self.assertEqual(publication_issues(content), [])
        company = {"company_name": "A store", "email": None, "address": None}
        for kind in TENANT_KINDS:
            content = PolicyContent(**template(kind, company, "owner@example.com"))
            self.assertEqual(content.contact_email, "owner@example.com")
            self.assertEqual(content.currency, "INR")
            self.assertTrue(publication_issues(content))
            content.address = "Reviewed business address"
            content.jurisdiction = "Chennai"
            content.body = re.sub(r"\[\[.*?\]\]", "Reviewed store-specific terms.", content.body, flags=re.S)
            self.assertEqual(publication_issues(content), [])

    def test_invalid_email_unfinished_placeholders_and_currency_are_rejected(self):
        content = PolicyContent(**template("privacy"))
        for email in ["", "not-an-email", "x@@example.com"]:
            content.contact_email = email
            self.assertTrue(publication_issues(content))
        content.contact_email = "support@example.com"
        content.body = "[[Unfinished"
        self.assertTrue(publication_issues(content))
        with self.assertRaises(ValidationError):
            PolicyContent(**{**template("privacy"), "currency": "USD"})


class PolicyDatabaseTests(TenantDatabaseCase):
    def setUp(self):
        super().setUp()
        if not inspect(self.connection).has_table("legal_policies"):
            from alembic.migration import MigrationContext
            from alembic.operations import Operations
            migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "034_public_policies.py"))
            with Operations.context(MigrationContext.configure(self.connection)):
                migration["upgrade"]()

    def owner(self, prefix="policy"):
        tenant, cookies, email = self.register(prefix)
        headers = {**self.headers(cookies), "X-Tenant-Slug": tenant["user"]["tenant_slug"]}
        return tenant, cookies, headers, email

    def complete(self, content, body="Reviewed business practices. All prices are in INR."):
        return {**content, "address": "Reviewed street address, Chennai 600100",
                "jurisdiction": "Chennai", "body": body}

    def test_tenant_draft_publish_and_public_snapshot(self):
        tenant, cookies, headers, email = self.owner()
        drafts = self.client.get("/api/company/policies", headers=headers)
        self.assertEqual(drafts.status_code, 200, drafts.text)
        items = {item["kind"]: item for item in drafts.json()["items"]}
        self.assertEqual(set(items), set(TENANT_KINDS))
        self.assertEqual(items["privacy"]["content"]["contact_email"], email)
        self.assertEqual(items["privacy"]["content"]["business_name"], tenant["user"]["company_name"])
        self.assertEqual(items["privacy"]["revision"], 0)
        self.assertIsNone(items["privacy"]["published"])
        public_headers = {"X-Tenant-Slug": tenant["user"]["tenant_slug"]}
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/legal/tenant", headers=public_headers).json(), {"items": []})
        self.assertEqual(self.client.get("/api/legal/tenant/privacy", headers=public_headers).status_code, 404)
        self.assertEqual(self.client.get("/api/company/policies", headers=public_headers).status_code, 401)
        self.use_cookies(cookies)
        incomplete = self.client.put("/api/company/policies/shipping", json={
            "revision": 0, "content": items["shipping"]["content"]}, headers=headers)
        self.assertEqual(incomplete.status_code, 200, incomplete.text)
        refused = self.client.post("/api/company/policies/shipping/publish",
                                   json={"revision": 1, "reviewed": True}, headers=headers)
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertIn("placeholder", refused.text)
        content = self.complete(items["privacy"]["content"], "Public version one.")
        saved = self.client.put("/api/company/policies/privacy",
                                json={"revision": 0, "content": content}, headers=headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        revision = saved.json()["revision"]
        stale = self.client.put("/api/company/policies/privacy", json={"revision": 0, "content": content}, headers=headers)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.client.post("/api/company/policies/privacy/publish",
            json={"revision": revision, "reviewed": False}, headers=headers).status_code, 422)
        self.assertEqual(self.client.post("/api/company/policies/privacy/publish",
            json={"revision": revision, "reviewed": True}, headers=public_headers).status_code, 403)
        published = self.client.post("/api/company/policies/privacy/publish",
            json={"revision": revision, "reviewed": True}, headers=headers)
        self.assertEqual(published.status_code, 200, published.text)
        self.client.cookies.clear()
        public = self.client.get("/api/legal/tenant/privacy", headers=public_headers)
        self.assertEqual(public.status_code, 200, public.text)
        self.assertEqual(public.json()["content"], content)
        self.assertNotIn("draft", public.json())
        self.assertIn("no-store", public.headers["cache-control"])
        self.use_cookies(cookies)
        edited = self.client.put("/api/company/policies/privacy",
            json={"revision": revision, "content": {**content, "body": "Unpublished new draft."}}, headers=headers)
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(self.client.post("/api/company/policies/privacy/publish",
            json={"revision": revision, "reviewed": True}, headers=headers).status_code, 409)
        self.client.cookies.clear()
        unchanged = self.client.get("/api/legal/tenant/privacy", headers=public_headers)
        self.assertEqual(unchanged.json()["content"]["body"], "Public version one.")
        self.assertNotIn("content", self.client.get("/api/legal/tenant", headers=public_headers).json()["items"][0])
        with self.factory() as db:
            self.assertEqual(db.execute(text("""select count(*) from audit_events where company_id=:company
                and action='POLICY_PUBLISHED'"""), {"company": tenant["user"]["company_id"]}).scalar_one(), 1)

    def test_roles_hosts_and_tenant_isolation(self):
        first, cookies, headers, _ = self.owner("pol-first")
        kind = self.client.get("/api/company/policies", headers=headers).json()["items"][0]
        content = self.complete(kind["content"])
        self.assertEqual(self.client.put("/api/company/policies/privacy",
            json={"revision": 0, "content": content}, headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/api/company/policies/privacy/publish",
            json={"revision": 1, "reviewed": True}, headers=headers).status_code, 200)
        second, _, other_headers, _ = self.owner("pol-second")
        other = self.client.get("/api/company/policies", headers=other_headers)
        self.assertTrue(all(item["revision"] == 0 for item in other.json()["items"]))
        self.assertEqual(self.client.get("/api/company/policies", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/api/legal/tenant", headers=other_headers).json(), {"items": []})
        with self.factory() as db:
            db.execute(text("""update tenant_memberships set role='staff'
                where company_id=:company and user_id=:user"""),
                {"company": second["user"]["company_id"], "user": second["user"]["user_id"]})
            db.commit()
        self.assertEqual(self.client.get("/api/company/policies", headers=other_headers).status_code, 403)
        self.assertEqual(self.client.put("/api/company/policies/privacy",
            json={"revision": 0, "content": content}, headers=other_headers).status_code, 403)
        self.client.cookies.clear()
        slug = first["user"]["tenant_slug"]
        public = self.client.get("/api/legal/tenant/privacy", headers={"Host": f"{slug}.tenali-business.com"})
        self.assertEqual(public.status_code, 200, public.text)
        mismatch = self.client.get("/api/legal/tenant/privacy",
            headers={"Host": f"{slug}.tenali-business.com", "X-Tenant-Slug": second["user"]["tenant_slug"]})
        self.assertEqual(mismatch.status_code, 404)
        self.assertEqual(self.client.get("/api/legal/tenant/privacy").status_code, 422)
        self.assertEqual(self.client.get("/api/legal/platform/privacy", headers={"Host": "unconfigured.example"}).status_code, 404)
        with self.factory() as db:
            db.execute(text("update companies set is_active=false where id=:id"), {"id": first["user"]["company_id"]})
            db.commit()
        self.assertEqual(self.client.get("/api/legal/tenant/privacy", headers={"X-Tenant-Slug": slug}).status_code, 404)

    def test_platform_scope_manual_publish_and_access(self):
        _, _, headers, _ = self.owner("pol-platform")
        self.assertEqual(self.client.get("/api/platform/policies", headers=headers).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/platform/policies").status_code, 401)
        admin_id = str(uuid4())
        token = "policy-platform-" + self.suffix
        with self.factory() as db:
            db.execute(text("delete from legal_policies where company_id is null"))
            db.execute(text("""insert into platform_admins(id,email,display_name,password_hash)
                values(:id,:email,'Policy fixture','unused')"""), {"id": admin_id, "email": token + "@example.com"})
            db.execute(text("""insert into platform_sessions(token_hash,admin_id,expires_at)
                values(:token,:admin,now()+interval '1 hour')"""), {"token": token_digest(token), "admin": admin_id})
            db.commit()
        self.client.cookies.update({"tenali_platform": token, "tenali_platform_csrf": "policy-csrf"})
        platform_headers = {"Origin": "http://localhost", "X-CSRF-Token": "policy-csrf"}
        drafts = self.client.get("/api/platform/policies")
        self.assertEqual(drafts.status_code, 200, drafts.text)
        items = {item["kind"]: item for item in drafts.json()["items"]}
        self.assertEqual(set(items), set(PLATFORM_KINDS))
        self.assertEqual(self.client.put("/api/platform/policies/shipping",
            json={"revision": 0, "content": items["privacy"]["content"]}, headers=platform_headers).status_code, 404)
        content = items["privacy"]["content"]
        saved = self.client.put("/api/platform/policies/privacy",
            json={"revision": 0, "content": content}, headers=platform_headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertNotIn("privacy", [item["kind"] for item in self.client.get("/api/legal/platform").json()["items"]])
        self.assertEqual(self.client.post("/api/platform/policies/privacy/publish",
            json={"revision": 1, "reviewed": True}).status_code, 403)
        published = self.client.post("/api/platform/policies/privacy/publish",
            json={"revision": 1, "reviewed": True}, headers=platform_headers)
        self.assertEqual(published.status_code, 200, published.text)
        self.client.cookies.clear()
        public = self.client.get("/api/legal/platform/privacy")
        self.assertEqual(public.status_code, 200, public.text)
        self.assertEqual(public.json()["content"]["business_name"], "Sru Global (Tenali)")
        self.assertEqual(self.client.get("/api/company/policies").status_code, 401)
        with self.factory() as db:
            self.assertEqual(db.execute(text("""select count(*) from platform_audit
                where admin_id=:admin and action like 'POLICY_PUBLISHED:%'"""), {"admin": admin_id}).scalar_one(), 1)
