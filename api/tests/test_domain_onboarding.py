import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from types import SimpleNamespace

import dns.resolver
from fastapi import HTTPException, Request

from app.api.routes.auth import social_return_origin
from app.services import domain_onboarding as domains
from test_tenancy import TenantDatabaseCase


class DomainOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TENALI_CUSTOM_DOMAINS_ENABLED": "true", "TENALI_BASE_DOMAIN": "tenali.biz"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.row = {"id": str(uuid4()), "hostname": "sourcedbysru.in", "verification_token": "fixture-token",
                    "company_id": str(uuid4()), "verified_at": None, "hosting_status": "dns_pending"}

    def test_domain_and_related_api_alias_claims_are_reserved_together(self):
        self.assertEqual(domains.domain_hostnames("sourcedbysru.in"), [
            ("sourcedbysru.in", "web"), ("www.sourcedbysru.in", "alias"),
            ("api.sourcedbysru.in", "api"), ("www.api.sourcedbysru.in", "alias"),
        ])
        for hostname in ["tenali.biz", "shop.tenali.biz", "api.sourcedbysru.in",
                         "www.sourcedbysru.in", "tenant.onrender.com"]:
            with self.subTest(hostname=hostname), self.assertRaises(HTTPException):
                domains.validate_custom_hostname(hostname)

    def test_render_calls_cannot_precede_ownership_verification(self):
        with patch.object(domains, "txt_matches", side_effect=HTTPException(422, "Missing TXT")), \
                patch.object(domains, "reserve_bindings") as reserve:
            db = MagicMock()
            with self.assertRaises(HTTPException):
                domains.verify_ownership(db, self.row)
            reserve.assert_not_called()
            db.execute.assert_not_called()
        with patch.object(domains, "txt_matches") as verify, patch.object(domains, "reserve_bindings") as reserve:
            domains.verify_ownership(db, self.row)
            verify.assert_called_once_with("sourcedbysru.in", "fixture-token")
            reserve.assert_called_once()
            self.assertEqual(db.execute.call_args.args[1]["status"], "provisioning")

    def test_competing_binding_never_changes_owner(self):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        db.execute.return_value.scalar_one.return_value = str(uuid4())
        with self.assertRaises(HTTPException) as error:
            domains.reserve_bindings(db, self.row)
        self.assertEqual(error.exception.status_code, 409)

    def test_txt_validation_and_dns_errors_are_actionable(self):
        answer = MagicMock()
        answer.strings = [b"fixture-", b"token"]
        with patch.object(dns.resolver, "resolve", return_value=[answer]) as resolve:
            domains.txt_matches("sourcedbysru.in", "fixture-token")
            resolve.assert_called_once_with("_tenali-verification.sourcedbysru.in", "TXT", lifetime=5)
        with patch.object(dns.resolver, "resolve", side_effect=dns.resolver.NXDOMAIN):
            with self.assertRaises(HTTPException) as error:
                domains.txt_matches("sourcedbysru.in", "fixture-token")
            self.assertEqual(error.exception.status_code, 422)

    def test_godaddy_records_target_separate_render_services(self):
        records = domains.dns_records("sourcedbysru.in", "token", "web.onrender.com", "api.onrender.com", "216.24.57.1")
        self.assertEqual(records, [
            {"type": "TXT", "name": "_tenali-verification.sourcedbysru.in", "value": "token"},
            {"type": "A", "name": "sourcedbysru.in", "value": "216.24.57.1"},
            {"type": "CNAME", "name": "www.sourcedbysru.in", "value": "web.onrender.com"},
            {"type": "CNAME", "name": "api.sourcedbysru.in", "value": "api.onrender.com"},
        ])

    def test_central_social_callback_only_returns_to_verified_domains(self):
        request = Request({"type": "http", "method": "GET", "scheme": "https", "path": "/auth/social-return-origin",
                           "headers": [(b"host", b"tenali.biz")], "query_string": b""})
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with self.assertRaises(HTTPException) as error:
            social_return_origin("https://unverified.in", request, db)
        self.assertEqual(error.exception.status_code, 403)
        for origin in ["http://sourcedbysru.in", "https://sourcedbysru.in/evil", "https://sourcedbysru.in:443"]:
            with self.assertRaises(HTTPException):
                social_return_origin(origin, request, db)
        db.execute.return_value.scalar_one_or_none.return_value = str(uuid4())
        self.assertEqual(social_return_origin("https://sourcedbysru.in", request, db), {"allowed": True})

    def test_registration_intent_is_committed_before_any_provider_write(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.all.return_value = [
            {"hostname": "sourcedbysru.in", "kind": "web", "render_id": None, "provider_owned": False},
            {"hostname": "api.sourcedbysru.in", "kind": "api", "render_id": None, "provider_owned": False},
        ]
        with patch("app.services.render_domains.get_config", return_value=MagicMock()), \
                patch("app.services.render_domains.find_custom_domain", return_value=None), \
                patch("app.services.render_domains.ensure_custom_domain") as ensure:
            domains.provision_hosting(db, self.row)
        ensure.assert_not_called()
        self.assertTrue(any("provider_owned=true" in str(call.args[0]) for call in db.execute.call_args_list))
        self.assertEqual(db.execute.call_args.args[1]["status"], "provisioning")
        self.assertEqual(db.execute.call_args.args[1]["seconds"], 0)

    def test_uncertain_registration_is_reconciled_under_durable_ownership(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.all.return_value = [
            {"hostname": "sourcedbysru.in", "kind": "web", "render_id": None, "provider_owned": True},
            {"hostname": "api.sourcedbysru.in", "kind": "api", "render_id": None, "provider_owned": False},
        ]
        main = SimpleNamespace(hostname="sourcedbysru.in", id="remote-id")
        # A previous POST succeeded remotely but its response was lost.
        result = SimpleNamespace(domain=main, aliases=[], provider_owned=False)
        with patch("app.services.render_domains.get_config", return_value=MagicMock()), \
                patch("app.services.render_domains.ensure_custom_domain", return_value=result) as ensure, \
                patch.object(domains, "save_provider_binding") as save:
            domains.provision_hosting(db, self.row)
        ensure.assert_called_once()
        save.assert_called_once_with(db, self.row["id"], main, True)

    def test_render_verification_alone_never_marks_domain_active(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.all.return_value = [
            {"hostname": "sourcedbysru.in", "kind": "web", "render_id": "web-id", "provider_owned": True},
            {"hostname": "api.sourcedbysru.in", "kind": "api", "render_id": "api-id", "provider_owned": True},
        ]
        config = SimpleNamespace(web_host="web.onrender.com", api_host="api.onrender.com", apex_ip="216.24.57.1")
        with patch("app.services.render_domains.get_config", return_value=config), \
                patch("app.services.render_domains.get_custom_domain_status", side_effect=[
                    SimpleNamespace(hostname="sourcedbysru.in", ready=True),
                    SimpleNamespace(hostname="api.sourcedbysru.in", ready=True),
                ]), patch.object(domains, "https_ready", side_effect=HTTPException(422, "Certificate pending")):
            domains.provision_hosting(db, self.row)
        statuses = [call.args[1].get("status") for call in db.execute.call_args_list if len(call.args) > 1]
        self.assertIn("tls_pending", statuses)
        self.assertNotIn("active", statuses)
        self.assertEqual(db.execute.call_args.args[1]["error"], "Certificate pending")

    def test_cleanup_reconciles_uncertain_creations_and_preserves_external_entries(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.all.return_value = [
            {"hostname": "sourcedbysru.in", "kind": "web", "render_id": None, "provider_owned": True},
            {"hostname": "api.sourcedbysru.in", "kind": "api", "render_id": "external-id", "provider_owned": False},
        ]
        with patch("app.services.render_domains.get_config", return_value=MagicMock()), \
                patch("app.services.render_domains.find_custom_domain", return_value=SimpleNamespace(id="recovered-id")), \
                patch("app.services.render_domains.delete_custom_domain") as delete:
            domains.remove_hosting(db, self.row)
        delete.assert_called_once()
        self.assertEqual(delete.call_args.args[2:4], ("recovered-id", "sourcedbysru.in"))
        self.assertIn("delete from tenant_domains", str(db.execute.call_args.args[0]))

    def test_tls_probe_never_connects_to_untrusted_dns_addresses(self):
        with patch.object(dns.resolver, "resolve", side_effect=[["127.0.0.1"], ["216.24.57.1"]]), \
                patch.object(domains.socket, "create_connection") as connect:
            with self.assertRaises(HTTPException):
                domains.https_ready("sourcedbysru.in", "web.onrender.com", "216.24.57.1")
            connect.assert_not_called()


class DomainOnboardingDatabaseTests(TenantDatabaseCase):
    def test_verified_domain_binds_api_and_removal_disables_it_before_cleanup(self):
        from sqlalchemy import text
        account, cookies, _ = self.register("domain")
        host = "tenant-" + self.suffix + ".example.com"
        config = SimpleNamespace(web_host="web.onrender.com", api_host="api.onrender.com", apex_ip="216.24.57.1")
        with patch.dict(os.environ, {"TENALI_CUSTOM_DOMAINS_ENABLED": "true"}), \
                patch("app.services.render_domains.get_config", return_value=config), \
                patch.object(domains, "txt_matches"):
            added = self.client.post("/auth/domains", json={"hostname": host}, headers=self.headers(cookies))
            self.assertEqual(added.status_code, 201, added.text)
            domain_id = added.json()["items"][0]["id"]
            verified = self.client.post(f"/auth/domains/{domain_id}/verify", headers=self.headers(cookies))
            self.assertEqual(verified.status_code, 200, verified.text)
            with self.factory() as db:
                bindings = db.execute(text("select hostname from tenant_domain_bindings where domain_id=:id"),
                                      {"id": domain_id}).scalars().all()
            self.assertIn("api." + host, bindings)
            self.use_cookies(cookies)
            api_url = "https://api." + host + "/api/auth/session"
            accepted = self.client.get(api_url, headers={"Origin": "https://" + host})
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertEqual(accepted.json()["user"]["company_id"], account["user"]["company_id"])
            denied = self.client.get(api_url, headers={"Origin": "https://other.example.com"})
            self.assertEqual(denied.status_code, 403)
            self.use_cookies(cookies)
            removed = self.client.delete(f"/auth/domains/{domain_id}", headers=self.headers(cookies))
            self.assertEqual(removed.status_code, 200, removed.text)
            self.assertTrue(removed.json()["removing"])
            self.assertEqual(self.client.get(api_url, headers={"Origin": "https://" + host}).status_code, 404)
            domains.process_due_domains()
            listed = self.client.get("/auth/domains").json()
            self.assertEqual(listed["items"], [])
