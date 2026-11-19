import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from fastapi import HTTPException

from app.services import checkout_providers as providers


class CheckoutProviderErrorTests(unittest.TestCase):
    def test_shiprocket_login_omits_authorization_and_preserves_credentials(self):
        credentials = {"shiprocket_email": "api@example.com", "shiprocket_password": 'p@ss+"\\ word'}
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.side_effect = [
            b'{"token":"fresh-token"}',
            b'{"data":{"shipping_address":[{"pickup_location":"Primary"}]}}',
        ]
        with patch.object(providers, "build_opener", return_value=opener):
            providers.check_connection("shiprocket", credentials, "Primary")
        login = opener.open.call_args_list[0].args[0]
        self.assertEqual(login.full_url, "https://apiv2.shiprocket.in/v1/external/auth/login")
        self.assertEqual(login.get_method(), "POST")
        self.assertFalse(login.has_header("Authorization"))
        self.assertEqual(json.loads(login.data), {
            "email": credentials["shiprocket_email"], "password": credentials["shiprocket_password"],
        })
        pickup = opener.open.call_args_list[1].args[0]
        self.assertEqual(pickup.get_header("Authorization"), "Bearer fresh-token")

    def test_shiprocket_login_does_not_forward_a_stale_token(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"token":"fresh-token"}'
        with patch.object(providers, "build_opener", return_value=opener):
            providers.provider_request("shiprocket", "POST", "/auth/login", {"token": "stale-token"},
                                       {"email": "api@example.com", "password": "fixture-password"})
        self.assertFalse(opener.open.call_args.args[0].has_header("Authorization"))

    def test_razorpay_keeps_basic_authorization(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"items":[]}'
        with patch.object(providers, "build_opener", return_value=opener):
            providers.provider_request("razorpay", "GET", "/orders", {
                "razorpay_key_id": "fixture-key", "razorpay_key_secret": "fixture-secret",
            })
        self.assertEqual(opener.open.call_args.args[0].get_header("Authorization"),
                         "Basic Zml4dHVyZS1rZXk6Zml4dHVyZS1zZWNyZXQ=")

    def request_failure(self, error, method="POST", path="/auth/login"):
        opener = MagicMock()
        opener.open.side_effect = error
        with patch.object(providers, "build_opener", return_value=opener), self.assertRaises(HTTPException) as raised:
            providers.provider_request("shiprocket", method, path, {"token": "private-token"},
                                       {"email": "private@example.com", "password": "private-password"})
        self.assertEqual(raised.exception.status_code, 502)
        opener.open.assert_called_once()
        detail = raised.exception.detail
        for secret in ["private-token", "private-password", "private@example.com", "private-provider-response"]:
            self.assertNotIn(secret, detail)
        return detail

    def http_error(self, status):
        return HTTPError("https://apiv2.shiprocket.in/private", status, "private-provider-response",
                         {}, io.BytesIO(b'{"message":"private-provider-response"}'))

    def test_api_login_rejection_explains_credentials_without_shipment_warning(self):
        for status in [400, 401, 403, 422]:
            with self.subTest(status=status):
                detail = self.request_failure(self.http_error(status))
                self.assertIn(f"HTTP {status}", detail)
                self.assertIn("dedicated API user", detail)
                self.assertIn("does not create a shipment", detail)
                self.assertNotIn("shipment recovery", detail)

    def test_pickup_permissions_and_rate_limit_are_distinguishable(self):
        detail = self.request_failure(self.http_error(403), "GET", "/settings/company/pickup")
        self.assertIn("pickup-location lookup", detail)
        self.assertIn("permissions", detail)
        detail = self.request_failure(self.http_error(429), "GET", "/settings/company/pickup")
        self.assertIn("rate-limiting", detail)

    def test_uncertain_shipment_write_retains_no_duplicate_shipment_guidance(self):
        for error in [TimeoutError(), URLError("private-provider-response"), self.http_error(503),
                      self.http_error(422)]:
            with self.subTest(error=type(error).__name__):
                detail = self.request_failure(error, path="/orders/create/adhoc")
                self.assertIn("before retrying", detail)
                self.assertIn("shipment recovery", detail)

    def test_non_object_response_retains_uncertain_write_guidance(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b"[]"
        with patch.object(providers, "build_opener", return_value=opener), self.assertRaises(HTTPException) as raised:
            providers.provider_request("shiprocket", "POST", "/orders/create/adhoc", {"token": "private-token"})
        self.assertIn("shipment recovery", raised.exception.detail)

    def test_razorpay_authentication_failure_is_actionable_without_leaking_provider_body(self):
        opener = MagicMock()
        opener.open.side_effect = self.http_error(401)
        with patch.object(providers, "build_opener", return_value=opener), self.assertRaises(HTTPException) as raised:
            providers.provider_request("razorpay", "GET", "/orders", {
                "razorpay_key_id": "fixture-key", "razorpay_key_secret": "fixture-secret",
            })
        self.assertIn("HTTP 401", raised.exception.detail)
        self.assertIn("matching Test or Live key pair", raised.exception.detail)
        self.assertIn("does not create an order", raised.exception.detail)
        self.assertNotIn("private-provider-response", raised.exception.detail)

    def test_razorpay_order_failures_keep_reconciliation_guidance_and_safe_field(self):
        for status, expected in [(400, "amount"), (401, "key pair"), (403, "activation"),
                                 (429, "rate-limiting"), (503, "unavailable")]:
            opener = MagicMock()
            opener.open.side_effect = HTTPError("https://api.razorpay.com/v1/orders", status, "private",
                {}, io.BytesIO(b'{"error":{"field":"amount","description":"private-secret"}}'))
            with self.subTest(status=status), patch.object(providers, "build_opener", return_value=opener), \
                    self.assertRaises(HTTPException) as raised:
                providers.provider_request("razorpay", "POST", "/orders", {
                    "razorpay_key_id": "fixture-key", "razorpay_key_secret": "fixture-secret"})
            self.assertIn(f"HTTP {status}", raised.exception.detail)
            self.assertIn(expected, raised.exception.detail)
            self.assertIn("Reconcile provider status before retrying", raised.exception.detail)
            self.assertNotIn("private-secret", raised.exception.detail)

    def test_razorpay_unparseable_errors_and_timeouts_remain_safe_and_explicit(self):
        for error in [TimeoutError(), URLError("private-secret"),
                      HTTPError("https://api.razorpay.com/v1/orders", 400, "private", {}, io.BytesIO(b"<html>private-secret</html>"))]:
            opener = MagicMock()
            opener.open.side_effect = error
            with self.subTest(error=type(error).__name__), patch.object(providers, "build_opener", return_value=opener), \
                    self.assertRaises(HTTPException) as raised:
                providers.provider_request("razorpay", "POST", "/orders", {
                    "razorpay_key_id": "fixture-key", "razorpay_key_secret": "fixture-secret"})
            self.assertIn("before retrying", raised.exception.detail)
            self.assertNotIn("private-secret", raised.exception.detail)

    def test_documented_razorpay_http_400_errors_are_not_misclassified(self):
        for description, expected in [
                ("Authentication failed.", "matching Test or Live key pair"),
                ("The amount must be at least INR 1.00", "at least INR 1.00"),
                ("private-provider-response", "account configuration")]:
            with self.subTest(description=description):
                detail = providers.razorpay_failure("POST", "/orders", 400, {
                    "error": {"description": description}})
                self.assertIn(expected, detail)
                self.assertNotIn("private-provider-response", detail)
