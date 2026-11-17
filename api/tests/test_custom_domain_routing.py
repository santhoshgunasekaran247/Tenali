import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from app.api.routes.auth import check_origin, set_session
from app.services.custom_domain_routing import CustomDomainRouting
from app.services.customer_security import SHOP_COOKIE, SHOP_CSRF, check_write, set_cookies


class CustomDomainRoutingTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TENALI_CUSTOM_DOMAINS_ENABLED": "true", "TENALI_ENV": "production"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.lookup = patch("app.services.custom_domain_routing.api_frontend",
                            side_effect=lambda host: "sourcedbysru.in" if host == "api.sourcedbysru.in" else None)
        self.lookup.start()
        self.addCleanup(self.lookup.stop)
        app = FastAPI()

        @app.post("/api/auth/login")
        def login(request: Request, response: Response):
            check_origin(request)
            set_session(response, request, "staff-session")
            return {"host": request.url.hostname}

        @app.post("/api/shop/login")
        def shop_login(request: Request, response: Response):
            check_write(request)
            set_cookies(response, request, "shop-session", SHOP_COOKIE, SHOP_CSRF)
            return {"ok": True}

        @app.post("/api/shop/write")
        def shop_write(request: Request):
            check_write(request, SHOP_CSRF)
            return {"ok": True}

        app.add_middleware(CustomDomainRouting)
        self.client = TestClient(app, base_url="https://api.sourcedbysru.in")
        self.origin = {"Origin": "https://sourcedbysru.in"}

    def test_exact_origin_cors_and_host_only_cookies(self):
        response = self.client.post("/api/auth/login", headers=self.origin)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["host"], "sourcedbysru.in")
        self.assertEqual(response.headers["access-control-allow-origin"], self.origin["Origin"])
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertIn("X-Tenali-Staff-CSRF", response.headers["access-control-expose-headers"])
        self.assertEqual(response.headers["X-Tenali-Staff-CSRF"], self.client.cookies["tenali_csrf"])
        for cookie in response.headers.get_list("set-cookie"):
            self.assertIn("Secure", cookie)
            self.assertIn("SameSite=lax", cookie)
            self.assertNotIn("Domain=", cookie)

    def test_preflight_and_foreign_origin_rejection(self):
        headers = {**self.origin, "Access-Control-Request-Method": "POST",
                   "Access-Control-Request-Headers": "content-type,x-csrf-token,x-tenant-slug"}
        self.assertEqual(self.client.options("/api/auth/login", headers=headers).status_code, 200)
        for origin in ["https://evil.in", "https://other.sourcedbysru.in",
                       "http://sourcedbysru.in", "https://sourcedbysru.in:443", "null"]:
            with self.subTest(origin=origin):
                response = self.client.post("/api/auth/login", headers={"Origin": origin})
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("access-control-allow-origin", response.headers)

    def test_shopper_csrf_still_required_and_exposed_after_login(self):
        response = self.client.post("/api/shop/login", headers=self.origin)
        token = response.headers["X-Tenali-Shopper-CSRF"]
        self.assertEqual(self.client.post("/api/shop/write", headers=self.origin).status_code, 403)
        response = self.client.post("/api/shop/write", headers={**self.origin, "X-CSRF-Token": token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Tenali-Shopper-CSRF"], token)

    def test_forwarded_host_cannot_choose_binding(self):
        response = self.client.post("/api/auth/login", headers={
            **self.origin, "X-Forwarded-Host": "other.in", "Forwarded": "host=other.in",
        })
        self.assertEqual(response.json()["host"], "sourcedbysru.in")
        denied = self.client.post("/api/auth/login", headers={"Origin": "https://other.in"})
        self.assertEqual(denied.status_code, 403)

    def test_disabled_feature_keeps_same_origin_auth_rules(self):
        with patch.dict(os.environ, {"TENALI_CUSTOM_DOMAINS_ENABLED": "false"}):
            response = self.client.post("/api/auth/login", headers=self.origin)
            self.assertEqual(response.status_code, 403)
