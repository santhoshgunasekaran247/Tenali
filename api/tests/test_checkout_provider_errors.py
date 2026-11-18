import io
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from fastapi import HTTPException

from app.services import checkout_providers as providers


class CheckoutProviderErrorTests(unittest.TestCase):
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

    def test_razorpay_error_contract_is_unchanged(self):
        opener = MagicMock()
        opener.open.side_effect = self.http_error(401)
        with patch.object(providers, "build_opener", return_value=opener), self.assertRaises(HTTPException) as raised:
            providers.provider_request("razorpay", "GET", "/orders", {
                "razorpay_key_id": "fixture-key", "razorpay_key_secret": "fixture-secret",
            })
        self.assertEqual(raised.exception.detail,
                         "Razorpay could not complete the request. Reconcile provider status before retrying.")
