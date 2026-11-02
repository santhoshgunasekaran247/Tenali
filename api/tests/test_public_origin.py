import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from app.api.routes.auth import check_origin, set_session
from app.services.customer_security import check_write
from app.services.public_origin import PublicOriginMiddleware
from app.services.tenant_context import TenantBoundary, platform_host


PUBLIC = "https://tenali-web-dq3a.onrender.com"
API_HOST = "tenali-api.onrender.com"
ENV = {
    "TENALI_ENV": "production",
    "TENALI_BASE_DOMAIN": "tenali-web-dq3a.onrender.com",
    "TENALI_PUBLIC_ORIGIN": PUBLIC,
    "TENALI_API_HOST": API_HOST,
}


def test_app():
    app = FastAPI()

    @app.get("/api/auth/session")
    def session(request: Request):
        check_origin(request)
        return {"host": request.url.hostname, "platform": platform_host(request)}

    @app.post("/api/auth/login")
    def login(request: Request, response: Response):
        check_origin(request)
        check_write(request)
        set_session(response, request, "test-session")
        return {"host": request.url.hostname}

    @app.post("/api/platform/write")
    def platform_write(request: Request):
        check_write(request, "tenali_platform_csrf")
        return {"ok": True}

    @app.post("/api/private")
    def private_write():
        return {"ok": True}

    app.add_middleware(TenantBoundary)
    app.add_middleware(PublicOriginMiddleware)
    return app


class PublicOriginTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db = patch("app.services.tenant_context.SessionLocal")
        self.db.start()
        self.addCleanup(self.db.stop)
        self.host_company = patch("app.services.tenant_context.host_company", return_value=None)
        self.host_company.start()
        self.addCleanup(self.host_company.stop)
        self.client = TestClient(test_app(), base_url="https://" + API_HOST)

    def test_api_host_restored_to_public_origin(self):
        response = self.client.get("/api/auth/session")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"host": "tenali-web-dq3a.onrender.com", "platform": True})
        self.assertIn("no-store", response.headers["cache-control"])

    def test_login_accepts_only_public_origin_and_preserves_secure_cookies(self):
        response = self.client.post("/api/auth/login", headers={"Origin": PUBLIC})
        self.assertEqual(response.status_code, 200, response.text)
        cookies = response.headers.get_list("set-cookie")
        self.assertEqual(len(cookies), 2)
        self.assertTrue(all("Secure" in cookie and "SameSite=lax" in cookie for cookie in cookies))
        self.assertIn("HttpOnly", cookies[0])
        self.assertNotIn("HttpOnly", cookies[1])
        for origin in ["https://evil.example", "https://" + API_HOST]:
            with self.subTest(origin=origin):
                denied = self.client.post("/api/auth/login", headers={"Origin": origin})
                self.assertEqual(denied.status_code, 403)

    def test_platform_write_still_requires_csrf(self):
        self.client.cookies.set("tenali_platform_csrf", "test-csrf")
        self.assertEqual(self.client.post("/api/platform/write", headers={"Origin": PUBLIC}).status_code, 403)
        response = self.client.post("/api/platform/write", headers={
            "Origin": PUBLIC, "X-CSRF-Token": "test-csrf",
        })
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/platform/write", headers={
            "Origin": "https://evil.example", "X-CSRF-Token": "test-csrf",
        })
        self.assertEqual(response.status_code, 403)

    def test_tenant_write_still_checks_origin_csrf_and_session(self):
        from fastapi import HTTPException

        with patch("app.services.tenant_context.TenantAuth") as auth:
            auth.return_value.identity.side_effect = HTTPException(401, "Sign in")
            self.assertEqual(self.client.post("/api/private").status_code, 401)
            auth.return_value.identity.side_effect = None
            auth.return_value.identity.return_value = {"company_id": "company-a", "role": "owner"}
            self.client.cookies.set("tenali_csrf", "test-csrf")
            with patch("app.services.tenant_context.check_module"):
                self.assertEqual(self.client.post("/api/private", headers={"Origin": PUBLIC}).status_code, 403)
                headers = {"Origin": PUBLIC, "X-CSRF-Token": "test-csrf"}
                self.assertEqual(self.client.post("/api/private", headers=headers).status_code, 200)
                headers["Origin"] = "https://evil.example"
                self.assertEqual(self.client.post("/api/private", headers=headers).status_code, 403)
                headers["Origin"] = PUBLIC
                headers["X-Tenant-Slug"] = "another-workspace"
                with patch("app.services.tenant_context.company_by_slug", return_value={"id": "company-b"}):
                    self.assertEqual(self.client.post("/api/private", headers=headers).status_code, 403)

    def test_forwarded_headers_cannot_choose_public_host(self):
        response = self.client.get("/api/auth/session", headers={
            "Forwarded": "host=evil.example;proto=http",
            "X-Forwarded-Host": "evil.example",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["host"], "tenali-web-dq3a.onrender.com")
        response = self.client.get("/api/auth/session", headers={
            "Host": "unknown.example", "X-Forwarded-Host": API_HOST,
        })
        self.assertEqual(response.status_code, 404)

    def test_other_hosts_are_not_remapped(self):
        for host in ["tenant.example", "sourcebysru.tenali-web-dq3a.onrender.com"]:
            with self.subTest(host=host):
                self.assertEqual(self.client.get("/api/auth/session", headers={"Host": host}).status_code, 404)

    def test_disabled_mapping_preserves_existing_domain_checks(self):
        with patch.dict(os.environ, {"TENALI_API_HOST": "", "TENALI_PUBLIC_ORIGIN": ""}):
            client = TestClient(test_app(), base_url="https://" + API_HOST)
            self.assertEqual(client.get("/api/auth/session").status_code, 404)
            response = client.get("/api/auth/session", headers={"Host": "tenali-web-dq3a.onrender.com"})
            self.assertEqual(response.status_code, 200)

    def test_custom_domain_configuration(self):
        with patch.dict(os.environ, {"TENALI_BASE_DOMAIN": "tenali.biz", "TENALI_PUBLIC_ORIGIN": "https://tenali.biz"}):
            client = TestClient(test_app(), base_url="https://" + API_HOST)
            response = client.post("/api/auth/login", headers={"Origin": "https://tenali.biz"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["host"], "tenali.biz")
            self.assertEqual(client.post("/api/auth/login", headers={"Origin": PUBLIC}).status_code, 403)

    def test_real_app_platform_session_and_tenant_exclusion(self):
        from app.api.routes.auth import identity_db
        from app.main import create_app

        app = create_app()
        db = MagicMock()
        db.execute.return_value.mappings.return_value.first.return_value = None
        app.dependency_overrides[identity_db] = lambda: db
        client = TestClient(app, base_url="https://" + API_HOST)
        with patch("app.api.routes.platform.host_company", return_value=None):
            response = client.get("/api/platform/session")
            self.assertEqual(response.status_code, 401, response.text)
            self.assertEqual(response.json()["detail"], "Platform administrator sign-in required")
            self.assertEqual(client.get("/health").status_code, 200)
            client.cookies.set("tenali_session", "workspace-session")
            with patch("app.api.routes.platform.TenantAuth") as auth:
                auth.return_value.identity.return_value = {"company_id": "company-a", "role": "owner"}
                response = client.get("/api/platform/session")
                self.assertEqual(response.status_code, 403, response.text)
                self.assertIn("Workspace accounts cannot access", response.json()["detail"])
            client.cookies.clear()
            client.cookies.set("tenali_shopper", "shopper-session")
            db.execute.return_value.first.return_value = (1,)
            response = client.get("/api/platform/session")
            self.assertEqual(response.status_code, 403, response.text)
            self.assertIn("Shopper accounts cannot access", response.json()["detail"])

    def test_verified_tenant_hosts_keep_their_own_identity(self):
        with patch("app.services.tenant_context.host_company", return_value={"id": "company-a"}):
            response = self.client.get("/api/auth/session", headers={"Host": "store.example"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"host": "store.example", "platform": False})

    def test_invalid_configuration_fails_explicitly(self):
        for changes in [
            {"TENALI_API_HOST": ""},
            {"TENALI_PUBLIC_ORIGIN": ""},
            {"TENALI_API_HOST": "https://" + API_HOST},
            {"TENALI_PUBLIC_ORIGIN": "http://tenali-web-dq3a.onrender.com"},
            {"TENALI_PUBLIC_ORIGIN": PUBLIC + "/login"},
            {"TENALI_PUBLIC_ORIGIN": PUBLIC + "?x=1"},
            {"TENALI_PUBLIC_ORIGIN": "https://evil.example"},
            {"TENALI_PUBLIC_ORIGIN": "https://user:password@tenali-web-dq3a.onrender.com"},
        ]:
            with self.subTest(changes=changes), patch.dict(os.environ, changes):
                with self.assertRaises(ValueError):
                    PublicOriginMiddleware(MagicMock())
