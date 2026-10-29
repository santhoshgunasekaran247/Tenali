import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.schemas.checkout import CheckoutInput, CheckoutSettingsInput, DeliveryAddress
from app.services import checkout_providers as providers
from app.services.tenant_security import password_hash
from test_tenancy import TenantDatabaseCase


ADDRESS = {"name": "Test Shopper", "phone": "9876543210", "address": "123 Test Street",
           "city": "Chennai", "state": "Tamil Nadu", "pincode": "600001", "country": "India"}
CREDENTIALS = {"razorpay_key_id": "rzp_live_fixture", "razorpay_key_secret": "fixture-payment-secret",
               "razorpay_webhook_secret": "fixture-webhook-secret-long",
               "shiprocket_email": "api@example.invalid", "shiprocket_password": "fixture-shipping-password"}


class CheckoutSecurityTests(unittest.TestCase):
    def test_connection_checks_are_read_only_and_do_not_claim_activation(self):
        with patch.object(providers, "provider_request", return_value={"entity": "collection", "items": []}) as request:
            message = providers.check_connection("razorpay", CREDENTIALS, "Primary")
            request.assert_called_once_with("razorpay", "GET", "/orders?count=1", CREDENTIALS)
            self.assertIn("not KYC approval", message)
        with patch.object(providers, "provider_request", side_effect=[
                {"token": "fixture-token"}, {"data": {"shipping_address": [{"pickup_location": "Primary"}]}}]) as request:
            message = providers.check_connection("shiprocket", CREDENTIALS, "Primary")
            self.assertEqual([(call.args[1], call.args[2]) for call in request.call_args_list],
                             [("POST", "/auth/login"), ("GET", "/settings/company/pickup")])
            self.assertIn("No shipment was created", message)
        for responses in [
                [{"token": "fixture-token"}, {"data": {"shipping_address": []}}],
                [{"token": "fixture-token"}, {"data": {"shipping_address": "invalid"}}],
                [{"token": ""}]]:
            with patch.object(providers, "provider_request", side_effect=responses):
                with self.assertRaises(HTTPException):
                    providers.check_connection("shiprocket", CREDENTIALS, "Primary")
        with patch.object(providers, "provider_request", return_value={"items": "invalid"}):
            with self.assertRaises(HTTPException):
                providers.check_connection("razorpay", CREDENTIALS, "Primary")

    def test_encrypted_credentials_are_tenant_bound_and_fail_closed(self):
        with patch.dict(os.environ, {"TENALI_CREDENTIAL_KEY": Fernet.generate_key().decode()}):
            encrypted = providers.encrypt_credentials("tenant-a", CREDENTIALS)
            self.assertNotIn(CREDENTIALS["razorpay_key_secret"], encrypted)
            self.assertEqual(providers.decrypt_credentials("tenant-a", encrypted), CREDENTIALS)
            with self.assertRaises(HTTPException):
                providers.decrypt_credentials("tenant-b", encrypted)
            with patch.dict(os.environ, {"TENALI_CREDENTIAL_KEY": Fernet.generate_key().decode()}):
                with self.assertRaises(HTTPException):
                    providers.decrypt_credentials("tenant-a", encrypted)
        with patch.dict(os.environ, {"TENALI_CREDENTIAL_KEY": ""}):
            with self.assertRaises(HTTPException):
                providers.encrypt_credentials("tenant-a", CREDENTIALS)

    def test_payment_signature_capture_amount_currency_and_order_are_verified(self):
        message = b"order_fixture|pay_fixture"
        signature = hmac.new(b"fixture", message, hashlib.sha256).hexdigest()
        providers.verify_signature("fixture", message, signature)
        with self.assertRaises(HTTPException):
            providers.verify_signature("fixture", b"order_other|pay_fixture", signature)
        payment = {"order_id": "order_fixture", "amount": 10000, "currency": "INR", "status": "captured"}
        with patch.object(providers, "provider_request", return_value=payment):
            providers.captured_payment(CREDENTIALS, "order_fixture", "pay_fixture", 10000)
        for key, value in [("order_id", "order_other"), ("amount", 1), ("currency", "USD"), ("status", "authorized")]:
            with patch.object(providers, "provider_request", return_value={**payment, key: value}):
                with self.assertRaises(HTTPException):
                    providers.captured_payment(CREDENTIALS, "order_fixture", "pay_fixture", 10000)

    def test_checkout_rejects_price_injection_and_invalid_delivery(self):
        payload = {"request_key": str(uuid4()), "items": [{"product_id": str(uuid4()), "quantity": 1}], "address": ADDRESS}
        CheckoutInput(**payload)
        for patch_values in [{"items": [{**payload["items"][0], "unit_paise": 1}]}, {"items": [{**payload["items"][0], "quantity": 1.5}]},
                             *[{"items": [{**payload["items"][0], "quantity": quantity}]} for quantity in [0, -1, 101, True]],
                             {"items": payload["items"] * 31},
                             {"address": {**ADDRESS, "country": "US"}}, {"address": {**ADDRESS, "pincode": "000000"}}]:
            with self.assertRaises(ValidationError):
                CheckoutInput(**{**payload, **patch_values})
        settings = CheckoutSettingsInput(**CREDENTIALS, enabled=True, shipping_paise=0, pickup_location="Primary")
        self.assertNotIn(CREDENTIALS["razorpay_key_secret"], repr(settings))


class WorkspaceCredentialMigrationTests(TenantDatabaseCase):
    def prepare_legacy_accounts(self):
        self.legacy_companies = [str(uuid4()), str(uuid4())]
        self.legacy_user = str(uuid4())
        self.legacy_email = uuid4().hex + "@example.invalid"
        self.legacy_hash = password_hash("Legacy fixture password 123!")
        for company in self.legacy_companies:
            self.connection.execute(text("insert into companies(id,company_name,tenant_slug) values(:id,'Legacy fixture',:slug)"),
                                    {"id": company, "slug": "legacy-fixture-" + company})
        self.connection.execute(text("insert into tenant_users(id,email,display_name,password_hash) values(:id,:email,'Legacy owner',:hash)"),
                                {"id": self.legacy_user, "email": self.legacy_email, "hash": self.legacy_hash})
        for index, company in enumerate(self.legacy_companies):
            self.connection.execute(text("insert into tenant_memberships(company_id,user_id,role) values(:company,:user,'owner')"),
                                    {"company": company, "user": self.legacy_user})
            self.connection.execute(text("""insert into tenant_sessions(token_hash,user_id,company_id,expires_at)
                values(:token,:user,:company,now()+interval '1 hour')"""),
                {"token": f"legacy-fixture-{self.legacy_user}-{index}", "user": self.legacy_user, "company": company})

    def test_existing_memberships_keep_passwords_but_become_independent(self):
        from app.services.tenant_security import password_matches
        if not hasattr(self, "legacy_companies"):
            self.skipTest("Migration fixture requires the pre-018 schema")
        with self.factory() as db:
            accounts = db.execute(text("select id,company_id,password_hash from tenant_users where email=:email order by company_id"),
                                  {"email": self.legacy_email}).mappings().all()
            self.assertEqual(len(accounts), 2)
            self.assertNotEqual(accounts[0]["id"], accounts[1]["id"])
            self.assertTrue(all(account["password_hash"] == self.legacy_hash for account in accounts))
            for account in accounts:
                session_user = db.execute(text("select user_id from tenant_sessions where company_id=:company and user_id=:user"),
                                          {"company": account["company_id"], "user": account["id"]}).scalar_one()
                self.assertEqual(session_user, account["id"])
            db.execute(text("update tenant_users set password_hash=:hash where id=:id"),
                       {"hash": password_hash("Changed workspace fixture 123!"), "id": accounts[0]["id"]})
            untouched = db.execute(text("select password_hash from tenant_users where id=:id"), {"id": accounts[1]["id"]}).scalar_one()
            self.assertTrue(password_matches("Legacy fixture password 123!", untouched))


class ShopperCheckoutTests(TenantDatabaseCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"TENALI_CREDENTIAL_KEY": Fernet.generate_key().decode()}))
        self.first, self.staff_cookies, self.staff_email = self.register("shop-a")
        self.company_id = self.first["user"]["company_id"]
        self.slug = self.first["user"]["tenant_slug"]
        self.provider_calls = []
        self.payment_amount = 10500
        self.provider_order = "order_" + self.suffix
        self.stack.enter_context(patch.object(providers, "provider_request", self.provider))

    def provider(self, provider, method, path, credentials, payload=None):
        self.provider_calls.append((provider, method, path, payload))
        if provider == "razorpay" and path == "/orders?count=1":
            return {"entity": "collection", "items": []}
        if provider == "shiprocket" and path == "/settings/company/pickup":
            return {"data": {"shipping_address": [{"pickup_location": "Primary"}]}}
        if provider == "razorpay" and path == "/orders":
            self.payment_amount = payload["amount"]
            return {"id": self.provider_order, "amount": payload["amount"], "currency": payload["currency"]}
        if provider == "razorpay" and path.startswith("/payments/"):
            return {"id": path.split("/")[-1], "order_id": self.provider_order, "amount": self.payment_amount, "currency": "INR", "status": "captured"}
        if path == "/auth/login":
            return {"token": "fixture-token"}
        if path == "/orders/create/adhoc":
            return {"order_id": 12345, "shipment_id": 67890}
        raise AssertionError(f"Unexpected provider call {provider} {method} {path}")

    def staff_headers(self):
        return {**self.headers(self.staff_cookies), "X-Tenant-Slug": self.slug}

    def shop_headers(self):
        cookies = dict(self.client.cookies)
        return {"Origin": "http://localhost", "X-Tenant-Slug": self.slug, "X-CSRF-Token": cookies.get("tenali_shopper_csrf", "")}

    def create_shopper(self, email=None, password="Shopper fixture password 123!"):
        response = self.client.post("/shop/register", json={"email": email or self.staff_email, "display_name": "Shopper", "password": password},
                                    headers={"Origin": "http://localhost", "X-Tenant-Slug": self.slug})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def configure(self):
        response = self.client.put("/checkout-admin/settings",
                                  json={**CREDENTIALS, "enabled": True, "shipping_paise": 500, "pickup_location": "Primary"},
                                  headers=self.staff_headers())
        self.assertEqual(response.status_code, 200, response.text)
        read = self.client.get("/checkout-admin/settings", headers=self.staff_headers())
        self.assertNotIn("secret", read.text)
        self.assertNotIn(CREDENTIALS["shiprocket_password"], read.text)

    def test_setup_updates_keep_credentials_and_connection_checks_are_workspace_scoped(self):
        base = {"enabled": False, "shipping_paise": 2500, "pickup_location": "Primary"}
        missing = self.client.put("/checkout-admin/settings", json=base, headers=self.staff_headers())
        self.assertEqual(missing.status_code, 422, missing.text)
        self.configure()
        read = self.client.get("/checkout-admin/settings", headers=self.staff_headers())
        self.assertEqual(read.json()["payment_mode"], "live")
        changed = self.client.put("/checkout-admin/settings", json=base, headers=self.staff_headers())
        self.assertEqual(changed.status_code, 200, changed.text)
        for partial in [{"razorpay_key_id": "rzp_test_other"}, {"shiprocket_password": "different"}]:
            response = self.client.put("/checkout-admin/settings", json={**base, **partial}, headers=self.staff_headers())
            self.assertEqual(response.status_code, 422, response.text)
        with self.factory() as db:
            stored = db.execute(text("select credentials from checkout_settings where company_id=:company"),
                                {"company": self.company_id}).scalar_one()
            self.assertEqual(providers.decrypt_credentials(self.company_id, stored), CREDENTIALS)
        for provider in ["razorpay", "shiprocket"]:
            response = self.client.post("/checkout-admin/settings/check/" + provider, headers=self.staff_headers())
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "passed")
            self.assertNotIn("fixture-token", response.text)
            self.assertNotIn(CREDENTIALS["razorpay_key_secret"], response.text)
        self.assertFalse(any(call[2] == "/orders/create/adhoc" or (call[0] == "razorpay" and call[1] == "POST") for call in self.provider_calls))
        with patch.object(providers, "provider_request", side_effect=HTTPException(502, "Provider connection failed")):
            failed = self.client.post("/checkout-admin/settings/check/razorpay", headers=self.staff_headers())
            self.assertEqual(failed.status_code, 200, failed.text)
            self.assertEqual(failed.json()["status"], "failed")
        self.assertEqual(self.client.post("/checkout-admin/settings/check/razorpay", headers={"Origin": "http://localhost"}).status_code, 403)
        self.assertEqual(self.client.post("/checkout-admin/settings/check/unsupported", headers=self.staff_headers()).status_code, 422)
        second, cookies, _ = self.register("shop-check-b")
        no_access = self.client.post("/checkout-admin/settings/check/razorpay",
                                     headers={**self.headers(cookies), "X-Tenant-Slug": self.slug})
        self.assertEqual(no_access.status_code, 403, no_access.text)
        no_settings = self.client.post("/checkout-admin/settings/check/razorpay",
                                       headers={**self.headers(cookies), "X-Tenant-Slug": second["user"]["tenant_slug"]})
        self.assertEqual(no_settings.status_code, 409, no_settings.text)

    def test_test_mode_payment_cannot_create_real_shiprocket_shipment(self):
        test_settings = {**CREDENTIALS, "razorpay_key_id": "rzp_test_fixture", "enabled": True,
                         "shipping_paise": 500, "pickup_location": "Primary"}
        configured = self.client.put("/checkout-admin/settings", json=test_settings, headers=self.staff_headers())
        self.assertEqual(configured.status_code, 200, configured.text)
        self.assertEqual(self.client.get("/checkout-admin/settings", headers=self.staff_headers()).json()["payment_mode"], "test")
        self.create_shopper()
        order, _ = self.checkout(self.product())
        paid = self.client.post(f"/shop/orders/{order['id']}/confirm", json=self.confirmation(order), headers=self.shop_headers())
        self.assertEqual(paid.status_code, 200, paid.text)
        blocked = self.client.post(f"/checkout-admin/orders/{order['id']}/ship",
                                   json={"weight": 1, "length": 10, "width": 10, "height": 10}, headers=self.staff_headers())
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("test payment", blocked.text)
        self.assertFalse(any(call[0] == "shiprocket" for call in self.provider_calls))

    def product(self, minimum=1, stock=2):
        with self.factory() as db:
            product_id = db.execute(text("""insert into products(company_id,portal_product_id,name,mrp,selling_price,pricing_mode,catalog_visible,minimum_order_quantity)
                values(:company,:code,'Shop fixture',200,100,'price',true,:minimum) returning id"""),
                {"company": self.company_id, "code": uuid4().hex, "minimum": minimum}).scalar_one()
            db.execute(text("insert into stock_balances(company_id,product_id,quantity) values(:company,:product,:quantity)"),
                       {"company": self.company_id, "product": product_id, "quantity": stock})
            db.commit()
        return str(product_id)

    def test_multi_item_cart_enforces_current_minimums_and_single_shipping_charge(self):
        self.configure()
        first = self.product(minimum=3, stock=20)
        second = self.product(minimum=2, stock=20)
        variant_response = self.client.post(f"/inventory/products/{first}/variants",
            json={"variant_name": "Blue"}, headers=self.staff_headers())
        self.assertEqual(variant_response.status_code, 201, variant_response.text)
        variant = str(variant_response.json()["variants"][0]["id"])
        with self.factory() as db:
            db.execute(text("""insert into stock_balances(company_id,product_id,variant_id,quantity)
                values(:company,:product,:variant,20)"""), {"company": self.company_id, "product": first, "variant": variant})
            db.commit()
        catalog = self.client.get(f"/catalog/products/{first}", headers={"X-Tenant-Slug": self.slug})
        self.assertEqual(catalog.status_code, 200, catalog.text)
        self.assertEqual(catalog.json()["product"]["minimum_order_quantity"], 3)
        self.create_shopper()
        payload = {"request_key": str(uuid4()), "items": [
            {"product_id": first, "variant_id": variant, "quantity": 3},
            {"product_id": second, "quantity": 2}], "address": ADDRESS}
        for path in ["/shop/quote", "/shop/orders"]:
            for index in [0, 1]:
                items = [dict(item) for item in payload["items"]]
                items[index]["quantity"] -= 1
                rejected = self.client.post(path, json={**payload, "items": items, "expected_total_paise": 50500},
                                            headers=self.shop_headers())
                self.assertEqual(rejected.status_code, 422, rejected.text)
                self.assertIn("Minimum order", rejected.text)
        self.assertEqual(self.provider_calls, [])
        quote = self.client.post("/shop/quote", json=payload, headers=self.shop_headers())
        self.assertEqual(quote.status_code, 200, quote.text)
        self.assertEqual(quote.json()["subtotal_paise"], 50000)
        self.assertEqual(quote.json()["shipping_paise"], 500)
        self.assertEqual(quote.json()["total_paise"], 50500)
        duplicate = self.client.post("/shop/quote", json={**payload, "items": [payload["items"][0]] * 2}, headers=self.shop_headers())
        self.assertEqual(duplicate.status_code, 422, duplicate.text)
        # A saved cart and quote must not bypass a newly increased product minimum.
        with self.factory() as db:
            db.execute(text("update products set minimum_order_quantity=4 where id=:id"), {"id": first})
            db.commit()
        stale = self.client.post("/shop/orders", json={**payload, "expected_total_paise": 50500}, headers=self.shop_headers())
        self.assertEqual(stale.status_code, 422, stale.text)
        payload["items"][0]["quantity"] = 4
        payload["expected_total_paise"] = 60500
        created = self.client.post("/shop/orders", json=payload, headers=self.shop_headers())
        self.assertEqual(created.status_code, 201, created.text)
        order = created.json()
        self.assertEqual(len(order["items"]), 2)
        self.assertEqual(order["shipping_paise"], 500)
        self.assertEqual(order["total_paise"], 60500)
        paid = self.client.post(f"/shop/orders/{order['id']}/confirm", json=self.confirmation(order), headers=self.shop_headers())
        self.assertEqual(paid.status_code, 200, paid.text)
        with self.factory() as db:
            quantities = db.execute(text("""select product_id,quantity from stock_balances where company_id=:company
                and (variant_id=:variant or product_id=:second)"""),
                {"company": self.company_id, "variant": variant, "second": second}).mappings().all()
            self.assertEqual({str(row["product_id"]): row["quantity"] for row in quantities}, {first: 16, second: 18})

    def test_minimum_quantity_is_editable_only_inside_own_workspace(self):
        product = self.product()
        payload = {"name": "Minimum fixture", "selling_price": 100, "minimum_order_quantity": 5}
        saved = self.client.put(f"/inventory/products/{product}", json=payload, headers=self.staff_headers())
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["minimum_order_quantity"], 5)
        second, cookies, _ = self.register("minimum-other")
        denied = self.client.put(f"/inventory/products/{product}", json={**payload, "minimum_order_quantity": 1},
            headers={**self.headers(cookies), "X-Tenant-Slug": second["user"]["tenant_slug"]})
        self.assertEqual(denied.status_code, 404, denied.text)
        with self.factory() as db:
            self.assertEqual(db.execute(text("select minimum_order_quantity from products where id=:id"),
                                       {"id": product}).scalar_one(), 5)

    def checkout(self, product_id):
        payload = {"request_key": str(uuid4()), "items": [{"product_id": product_id, "quantity": 1}], "address": ADDRESS}
        quote = self.client.post("/shop/quote", json=payload, headers=self.shop_headers())
        self.assertEqual(quote.status_code, 200, quote.text)
        self.assertEqual(quote.json()["total_paise"], 10500)
        payload["expected_total_paise"] = quote.json()["total_paise"]
        created = self.client.post("/shop/orders", json=payload, headers=self.shop_headers())
        self.assertEqual(created.status_code, 201, created.text)
        return created.json(), payload

    def confirmation(self, order, suffix=""):
        payment_id = "pay_" + self.suffix + suffix
        return {"razorpay_order_id": order["razorpay_order_id"], "razorpay_payment_id": payment_id,
                "razorpay_signature": hmac.new(CREDENTIALS["razorpay_key_secret"].encode(),
                                               (order["razorpay_order_id"] + "|" + payment_id).encode(), hashlib.sha256).hexdigest()}

    def test_staff_credentials_are_workspace_scoped_and_realms_are_separate(self):
        second_slug = "shop-b-" + self.suffix
        second_password = "Different workspace fixture password 123!"
        response = self.client.post("/auth/register", json={"company_name": "Shop B", "slug": second_slug, "display_name": "Same email",
                                                           "email": self.staff_email, "password": second_password},
                                    headers={"Origin": "http://localhost"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotEqual(response.json()["user"]["user_id"], self.first["user"]["user_id"])
        for slug, password, expected in [(second_slug, "Test password for tenancy 123!", 401),
                                         (self.slug, second_password, 401), (second_slug, second_password, 200)]:
            login = self.client.post("/auth/login", json={"email": self.staff_email, "password": password},
                                     headers={"Origin": "http://localhost", "X-Tenant-Slug": slug})
            self.assertEqual(login.status_code, expected, login.text)
        self.assertEqual(self.client.post("/auth/login", json={"email": self.staff_email, "password": second_password},
                                         headers={"Origin": "http://localhost"}).status_code, 422)
        self.client.cookies.clear()
        self.create_shopper()
        self.assertEqual(self.client.get("/parties", headers={"X-Tenant-Slug": self.slug}).status_code, 401)
        self.assertEqual(self.client.get("/platform/session").status_code, 401)
        self.assertEqual(self.client.get("/shop/session", headers={"X-Tenant-Slug": second_slug}).status_code, 401)
        self.assertEqual(self.client.post("/shop/password", json={"current_password": "Shopper fixture password 123!", "new_password": "New shopper fixture password 123!"},
                                         headers={"Origin": "http://localhost", "X-Tenant-Slug": self.slug}).status_code, 403)

    def test_checkout_is_idempotent_stock_safe_and_only_verified_capture_can_ship(self):
        self.configure()
        product_id = self.product()
        self.create_shopper()
        order, payload = self.checkout(product_id)
        self.assertNotIn("credentials", order)
        self.assertEqual(order["status"], "awaiting_payment")
        replay = self.client.post("/shop/orders", json=payload, headers=self.shop_headers())
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json()["id"], order["id"])
        self.assertEqual(sum(call[2] == "/orders" for call in self.provider_calls), 1)
        tamper = self.client.post("/shop/orders", json={**payload, "expected_total_paise": 1}, headers=self.shop_headers())
        self.assertEqual(tamper.status_code, 409)
        ship = self.client.post(f"/checkout-admin/orders/{order['id']}/ship", json={"weight": 1, "length": 10, "width": 10, "height": 10}, headers=self.staff_headers())
        self.assertEqual(ship.status_code, 409, ship.text)
        self.assertFalse(any(call[0] == "shiprocket" for call in self.provider_calls))
        self.assertEqual(self.client.post(f"/shop/orders/{order['id']}/confirm", json={**self.confirmation(order), "razorpay_signature": "0"*64},
                                         headers=self.shop_headers()).status_code, 400)
        for _ in range(2):
            paid = self.client.post(f"/shop/orders/{order['id']}/confirm", json=self.confirmation(order), headers=self.shop_headers())
            self.assertEqual(paid.status_code, 200, paid.text)
            self.assertEqual(paid.json()["status"], "paid")
        with self.factory() as db:
            quantity = db.execute(text("select sum(quantity) from stock_balances where company_id=:company and product_id=:product"),
                                  {"company": self.company_id, "product": product_id}).scalar_one()
            self.assertEqual(quantity, 1)
            self.assertEqual(db.execute(text("select count(*) from stock_movements where reference_type='shop_order' and reference_id=:id"),
                                        {"id": order["id"]}).scalar_one(), 1)
        for _ in range(2):
            shipped = self.client.post(f"/checkout-admin/orders/{order['id']}/ship", json={"weight": 1, "length": 10, "width": 10, "height": 10},
                                       headers=self.staff_headers())
            self.assertEqual(shipped.status_code, 200, shipped.text)
            self.assertEqual(shipped.json()["status"], "shipment_booked")
        self.assertEqual(sum(call[2] == "/orders/create/adhoc" for call in self.provider_calls), 1)

    def test_shopper_orders_stock_reservations_and_webhooks_are_scoped(self):
        self.configure()
        product_id = self.product()
        self.create_shopper()
        order, _ = self.checkout(product_id)
        first_cookies = dict(self.client.cookies)
        self.client.cookies.clear()
        self.create_shopper("other-" + self.staff_email)
        self.assertEqual(self.client.get("/shop/orders", headers=self.shop_headers()).json()["items"], [])
        self.assertEqual(self.client.post(f"/shop/orders/{order['id']}/confirm", json=self.confirmation(order), headers=self.shop_headers()).status_code, 404)
        self.use_cookies(first_cookies)
        self.assertEqual(self.client.post("/inventory/products/" + product_id + "/stock",
                                         json={"direction": "OUT", "quantity": 2, "notes": "Reserved check", "idempotency_key": str(uuid4())},
                                         headers=self.staff_headers()).status_code, 422)
        payload = {"event": "payment.captured", "payload": {"payment": {"entity": {
            "id": "pay_" + self.suffix, "order_id": order["razorpay_order_id"]}}}}
        body = json.dumps(payload).encode()
        signature = hmac.new(CREDENTIALS["razorpay_webhook_secret"].encode(), body, hashlib.sha256).hexdigest()
        rotated = self.client.put("/checkout-admin/settings",
                                  json={**CREDENTIALS, "razorpay_webhook_secret": "different-future-webhook-secret",
                                        "enabled": True, "shipping_paise": 500, "pickup_location": "Primary"},
                                  headers=self.staff_headers())
        self.assertEqual(rotated.status_code, 200, rotated.text)
        self.assertEqual(self.client.post("/shop/webhooks/razorpay/" + self.slug, content=body,
                                         headers={"X-Razorpay-Signature": "0"*64}).status_code, 400)
        for _ in range(2):
            result = self.client.post("/shop/webhooks/razorpay/" + self.slug, content=body,
                                      headers={"X-Razorpay-Signature": signature})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["status"], "paid")
        self.provider_order += "late"
        late, _ = self.checkout(product_id)
        with self.factory() as db:
            db.execute(text("update shop_orders set created_at=now()-interval '31 minutes' where id=:id"), {"id": late["id"]})
            db.execute(text("update stock_balances set quantity=0 where company_id=:company and product_id=:product"),
                       {"company": self.company_id, "product": product_id})
            db.commit()
        reviewed = self.client.post(f"/shop/orders/{late['id']}/confirm", json=self.confirmation(late, "late"), headers=self.shop_headers())
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["status"], "payment_review")
        blocked = self.client.post(f"/checkout-admin/orders/{late['id']}/ship", json={"weight": 1, "length": 10, "width": 10, "height": 10}, headers=self.staff_headers())
        self.assertEqual(blocked.status_code, 409, blocked.text)
        with self.factory() as db:
            events = db.execute(text("select new_value from audit_events where entity_type='shop_order' and entity_id=:id"),
                                {"id": late["id"]}).scalars().all()
            self.assertTrue(events)
            self.assertTrue(all("credentials" not in event and "address" not in event for event in events))

    def test_platform_admin_cannot_reuse_staff_sessions_and_suspension_revokes_sessions(self):
        self.assertEqual(self.client.get("/platform/workspaces").status_code, 401)
        with self.factory() as db:
            db.execute(text("insert into platform_admins(email,display_name,password_hash) values(:email,'Operator',:hash)"),
                       {"email": self.staff_email, "hash": password_hash("Platform fixture password 123!")})
            db.commit()
        self.assertEqual(self.client.post("/platform/login", json={"email": self.staff_email, "password": "Test password for tenancy 123!"},
                                         headers={"Origin": "http://localhost"}).status_code, 401)
        self.assertEqual(self.client.post("/platform/login", json={"email": self.staff_email, "password": "Platform fixture password 123!"},
                                         headers={"Origin": "http://localhost", "X-Tenant-Slug": self.slug}).status_code, 403)
        signed_in = self.client.post("/platform/login", json={"email": self.staff_email, "password": "Platform fixture password 123!"},
                                     headers={"Origin": "http://localhost"})
        self.assertEqual(signed_in.status_code, 200, signed_in.text)
        self.create_shopper()
        csrf = self.client.cookies.get("tenali_platform_csrf")
        disabled = self.client.patch("/platform/workspaces/" + self.company_id, json={"is_active": False},
                                    headers={"Origin": "http://localhost", "X-CSRF-Token": csrf})
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertEqual(self.client.get("/auth/session").status_code, 401)
        self.assertEqual(self.client.get("/shop/session", headers={"X-Tenant-Slug": self.slug}).status_code, 404)
        enabled = self.client.patch("/platform/workspaces/" + self.company_id, json={"is_active": True},
                                   headers={"Origin": "http://localhost", "X-CSRF-Token": csrf})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertEqual(self.client.get("/shop/session", headers={"X-Tenant-Slug": self.slug}).status_code, 401)

    def test_uncertain_shipment_is_not_resubmitted_and_reconciliation_is_order_bound(self):
        self.configure()
        product_id = self.product()
        self.create_shopper()
        order, _ = self.checkout(product_id)
        paid = self.client.post(f"/shop/orders/{order['id']}/confirm", json=self.confirmation(order), headers=self.shop_headers())
        self.assertEqual(paid.status_code, 200, paid.text)
        original_provider = self.provider
        def uncertain(provider, method, path, credentials, payload=None):
            if path == "/orders/create/adhoc":
                raise HTTPException(502, "Fixture: response lost after provider accepted order")
            return original_provider(provider, method, path, credentials, payload)
        package = {"weight": 1, "length": 10, "width": 10, "height": 10}
        with patch.object(providers, "provider_request", uncertain):
            result = self.client.post(f"/checkout-admin/orders/{order['id']}/ship", json=package, headers=self.staff_headers())
            self.assertEqual(result.status_code, 502, result.text)
        retry = self.client.post(f"/checkout-admin/orders/{order['id']}/ship", json=package, headers=self.staff_headers())
        self.assertEqual(retry.status_code, 409, retry.text)
        def remote(provider, method, path, credentials, payload=None):
            if path.startswith("/orders/show/"):
                return {"data": {"channel_order_id": order["id"] if path.endswith("/12345") else "another-order",
                                 "shipments": {"id": 67890, "awb": "TESTAWB", "courier": "Fixture Courier"}}}
            return original_provider(provider, method, path, credentials, payload)
        with patch.object(providers, "provider_request", remote):
            wrong = self.client.post(f"/checkout-admin/orders/{order['id']}/reconcile-shipment", json={"provider_order_id": 54321}, headers=self.staff_headers())
            self.assertEqual(wrong.status_code, 409, wrong.text)
            correct = self.client.post(f"/checkout-admin/orders/{order['id']}/reconcile-shipment", json={"provider_order_id": 12345}, headers=self.staff_headers())
            self.assertEqual(correct.status_code, 200, correct.text)
            self.assertEqual(correct.json()["status"], "shipment_booked")
            self.assertEqual(correct.json()["awb"], "TESTAWB")
