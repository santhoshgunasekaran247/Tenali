import base64
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
import httpx
from sqlalchemy import text

from app.services.customer_contacts import normalize_email, normalize_phone
from app.services import shopper_federation as federation
from test_tenancy import TenantDatabaseCase

CONFIG = {"enabled": True, "supabase": {"url": "https://abcdefghijklmnopqrst.supabase.co",
          "publicKey": "sb_publishable_public_fixture_key"}, "providers": ["google", "facebook", "custom:yahoo"]}
UID = "11111111-1111-4111-8111-111111111111"


def social_token(method="oauth", **changes):
    claims = {"sub": UID, "iss": CONFIG["supabase"]["url"] + "/auth/v1", "role": "authenticated",
              "amr": [{"method": method}], **changes}
    return "eyJhbGciOiJSUzI1NiJ9." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".fixture"


def social_user(provider="google"):
    return {"id": UID, "app_metadata": {"provider": provider}, "email": "editable@example.com",
            "user_metadata": {"email": "editable@example.com"},
            "identities": [{"provider": provider, "identity_data": {"email": "provider@example.com", "full_name": "Provider Buyer"}}]}


class CustomerContactTests(unittest.TestCase):
    def test_phone_normalization_and_email(self):
        for value in ["9876543210", "+91 98765 43210", "09876543210"]:
            self.assertEqual(normalize_phone(value, required=True), "+919876543210")
        self.assertEqual(normalize_phone("+1 202 555 0123"), "+12025550123")
        for value in ["", "123", "not a phone"]:
            with self.assertRaises(ValueError):
                normalize_phone(value, required=True)
        self.assertIsNone(normalize_phone(""))
        self.assertEqual(normalize_email(" Buyer@Example.COM "), "buyer@example.com")
        self.assertIsNone(normalize_email(""))
        for value in ["random", "x@@example.com", "x@localhost", "x y@example.com"]:
            with self.assertRaises(ValueError):
                normalize_email(value)

    def test_only_social_provider_profile_email_is_used(self):
        for provider in CONFIG["providers"]:
            with patch.object(federation.httpx, "get", return_value=httpx.Response(200, json=social_user(provider))) as verify:
                identity = federation.verified_identity(social_token(), CONFIG)
                self.assertEqual(identity["email"], "provider@example.com")
                self.assertEqual(identity["uid"], UID)
                self.assertEqual(verify.call_args.args[0], CONFIG["supabase"]["url"] + "/auth/v1/user")
                self.assertFalse(verify.call_args.kwargs["follow_redirects"])
        for method in ["password", "anonymous", "otp", "magiclink", "recovery", "email/signup"]:
            with patch.object(federation.httpx, "get", return_value=httpx.Response(200, json=social_user())):
                with self.assertRaises(HTTPException) as error:
                    federation.verified_identity(social_token(method), CONFIG)
                self.assertEqual(error.exception.status_code, 422)
        for provider in ["email", "phone", "github", None]:
            with patch.object(federation.httpx, "get", return_value=httpx.Response(200, json=social_user(provider))):
                with self.assertRaises(HTTPException) as error:
                    federation.verified_identity(social_token(), CONFIG)
                self.assertEqual(error.exception.status_code, 422)

    def test_invalid_revoked_and_unconfigured_login_fail_explicitly(self):
        for status, expected in [(401, 401), (403, 401), (429, 503), (500, 503), (302, 503)]:
            with patch.object(federation.httpx, "get", return_value=httpx.Response(status)):
                with self.assertRaises(HTTPException) as error:
                    federation.verified_identity("bad", CONFIG)
                self.assertEqual(error.exception.status_code, expected)
        with patch.object(federation.httpx, "get", side_effect=httpx.ConnectError("offline")):
            with self.assertRaises(HTTPException) as error:
                federation.verified_identity(social_token(), CONFIG)
            self.assertEqual(error.exception.status_code, 503)
        for config in [None, {**CONFIG, "enabled": False}]:
            with self.assertRaises(HTTPException) as error:
                federation.verified_identity("anything", config)
            self.assertEqual(error.exception.status_code, 503)
        for token in ["malformed", social_token(sub=str(uuid4())), social_token(iss="https://other.supabase.co/auth/v1")]:
            with patch.object(federation.httpx, "get", return_value=httpx.Response(200, json=social_user())):
                with self.assertRaises(HTTPException) as error:
                    federation.verified_identity(token, CONFIG)
                self.assertEqual(error.exception.status_code, 401)

    def test_social_profile_must_supply_email(self):
        user = {**social_user(), "identities": []}
        with patch.object(federation.httpx, "get", return_value=httpx.Response(200, json=user)):
            with self.assertRaises(HTTPException) as error:
                federation.verified_identity(social_token(), CONFIG)
            self.assertEqual(error.exception.status_code, 422)


class CustomerIdentityDatabaseTests(TenantDatabaseCase):
    def setUp(self):
        super().setUp()
        self.tenant, self.staff_cookies, _ = self.register("contacts")
        self.company = self.tenant["user"]["company_id"]
        self.slug = self.tenant["user"]["tenant_slug"]
        self.staff_headers = {**self.headers(self.staff_cookies), "X-Tenant-Slug": self.slug}

    def social(self, uid="buyer-one", email="online@example.com", phone="9876543210"):
        identity = {"uid": uid, "email": email, "name": "Online Buyer"}
        with patch.object(federation, "verified_identity", return_value=identity):
            result = self.client.post("/shop/federated", json={"id_token": "fixture", "phone": phone},
                                      headers={"Origin": "http://localhost", "X-Tenant-Slug": self.slug})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def counter(self, name="Counter Buyer", phone="9876543210"):
        self.use_cookies(self.staff_cookies)
        result = self.client.post("/billing/customers", json={"party_type": "customer", "legal_name": name, "phone": phone, "email": "counter@example.com"},
                                  headers=self.staff_headers)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def test_contacts_search_validation_and_same_phone_does_not_merge(self):
        missing = self.client.post("/billing/customers", json={"party_type": "customer", "legal_name": "Missing Phone"}, headers=self.staff_headers)
        self.assertEqual(missing.status_code, 422, missing.text)
        customer = self.counter()
        for query in ["Counter", "COUNTER@EXAMPLE", "987654", "98765 43210"]:
            found = self.client.get("/parties", params={"search": query}, headers=self.staff_headers)
            self.assertEqual([item["id"] for item in found.json()["items"]], [customer["id"]])
        duplicate_phone = self.counter("Family Buyer")
        self.assertNotEqual(customer["id"], duplicate_phone["id"])
        self.client.cookies.clear()
        online = self.social()
        self.assertEqual(online["phone"], "+919876543210")
        with self.factory() as db:
            account = db.execute(text("select customer_party_id from shopper_accounts where id=:id"), {"id": online["id"]}).scalar_one()
            self.assertIsNone(account)
            self.assertEqual(db.execute(text("select count(*) from parties where company_id=:company and system_role is null"), {"company": self.company}).scalar_one(), 2)
        headers = {"Origin": "http://localhost", "X-Tenant-Slug": self.slug, "X-CSRF-Token": self.client.cookies["tenali_shopper_csrf"]}
        edited = self.client.post("/shop/profile", json={"display_name": "Updated Buyer", "phone": "9123456789"}, headers=headers)
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["phone"], "+919123456789")
        self.assertEqual(self.client.get("/parties/online-customers", headers={"X-Tenant-Slug": self.slug}).status_code, 401)
        for path in ["/shop/register", "/shop/login"]:
            denied = self.client.post(path, json={"email": "random@example.com", "display_name": "Random", "password": "Random password long enough 123!"},
                                      headers={"Origin": "http://localhost", "X-Tenant-Slug": self.slug})
            self.assertEqual(denied.status_code, 410, denied.text)

    def test_manual_link_is_tenant_scoped_unique_and_audited(self):
        customer = self.counter()
        self.client.cookies.clear()
        online = self.social()
        other = self.social("buyer-two", "second@example.com")
        self.use_cookies(self.staff_cookies)
        listed = self.client.get("/parties/online-customers", headers=self.staff_headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual({item["id"] for item in listed.json()["items"]}, {online["id"], other["id"]})
        self.assertTrue(all(item["customer_party_id"] is None for item in listed.json()["items"]))
        invalid = self.client.post(f"/parties/online-customers/{online['id']}/link", json={"customer_party_id": str(uuid4())}, headers=self.staff_headers)
        self.assertEqual(invalid.status_code, 422, invalid.text)
        linked = self.client.post(f"/parties/online-customers/{online['id']}/link", json={"customer_party_id": customer["id"]}, headers=self.staff_headers)
        self.assertEqual(linked.status_code, 200, linked.text)
        conflict = self.client.post(f"/parties/online-customers/{other['id']}/link", json={"customer_party_id": customer["id"]}, headers=self.staff_headers)
        self.assertEqual(conflict.status_code, 409, conflict.text)
        replay = self.client.post(f"/parties/online-customers/{online['id']}/link", json={"customer_party_id": customer["id"]}, headers=self.staff_headers)
        self.assertEqual(replay.status_code, 200, replay.text)
        with self.factory() as db:
            self.assertEqual(db.execute(text("select count(*) from audit_events where company_id=:company and action='CUSTOMER_LINKED'"), {"company": self.company}).scalar_one(), 1)
        self.client.cookies.clear()
        second, second_cookies, _ = self.register("contacts-other")
        self.assertEqual(self.client.get("/parties/online-customers", headers=self.headers(second_cookies)).json()["items"], [])
        cross = self.client.post(f"/parties/online-customers/{online['id']}/link", json={"customer_party_id": customer["id"]}, headers=self.headers(second_cookies))
        self.assertEqual(cross.status_code, 404, cross.text)

    def test_same_social_identity_is_separate_per_tenant_and_legacy_email_not_claimed(self):
        first = self.social()
        second, cookies, _ = self.register("contacts-next")
        self.slug = second["user"]["tenant_slug"]
        self.client.cookies.clear()
        second_shopper = self.social()
        self.assertNotEqual(first["id"], second_shopper["id"])
        self.assertEqual(self.client.get("/shop/session", headers={"X-Tenant-Slug": self.tenant["user"]["tenant_slug"]}).status_code, 401)
        self.use_cookies(cookies)
        legacy_email = uuid4().hex + "@example.com"
        with self.factory() as db:
            db.execute(text("""insert into shopper_accounts(company_id,email,display_name,password_hash)
                values(:company,:email,'Legacy','x')"""), {"company": second["user"]["company_id"], "email": legacy_email})
            db.commit()
        with patch.object(federation, "verified_identity", return_value={"uid": "new-identity", "email": legacy_email, "name": "Claim"}):
            result = self.client.post("/shop/federated", json={"id_token": "fixture", "phone": "9876543210"},
                                      headers={"Origin": "http://localhost", "X-Tenant-Slug": self.slug})
        self.assertEqual(result.status_code, 409, result.text)
