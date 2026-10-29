import base64
import hashlib
import hmac
import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class NoProviderRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPException(502, "Provider redirected the request; refusing to forward credentials")


def cipher():
    key = os.getenv("TENALI_CREDENTIAL_KEY", "")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise HTTPException(503, "Checkout credential encryption is not configured. Ask the platform operator to set TENALI_CREDENTIAL_KEY on the API server; do not enter it in this form.") from error


def encrypt_credentials(company_id: str, credentials: dict) -> str:
    return cipher().encrypt(json.dumps({"company_id": str(company_id), "credentials": credentials}).encode()).decode()


def decrypt_credentials(company_id: str, encrypted: str) -> dict:
    try:
        data = json.loads(cipher().decrypt(encrypted.encode()))
    except (InvalidToken, ValueError, UnicodeError) as error:
        logger.error("Unable to decrypt checkout credentials for company %s", company_id)
        raise HTTPException(503, "Checkout credentials are unavailable; contact the workspace administrator") from error
    if data["company_id"] != str(company_id):
        raise HTTPException(503, "Checkout credentials do not belong to this workspace")
    return data["credentials"]


def provider_request(provider: str, method: str, path: str, credentials: dict, payload=None):
    if provider == "razorpay":
        base = "https://api.razorpay.com/v1"
        authorization = "Basic " + base64.b64encode(
            (credentials["razorpay_key_id"] + ":" + credentials["razorpay_key_secret"]).encode()).decode()
    else:
        base = "https://apiv2.shiprocket.in/v1/external"
        authorization = "Bearer " + credentials.get("token", "")
    headers = {"Content-Type": "application/json", "Authorization": authorization}
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(base + path, data=body, headers=headers, method=method)
    try:
        with build_opener(NoProviderRedirect()).open(request, timeout=20) as response:
            data = json.loads(response.read(2_000_000))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
        logger.warning("%s request failed (%s)", provider, type(error).__name__)
        raise HTTPException(502, f"{provider.title()} could not complete the request. Reconcile provider status before retrying.") from error
    if not isinstance(data, dict):
        raise HTTPException(502, f"{provider.title()} returned an invalid response")
    return data


def verify_signature(secret: str, message: bytes, signature: str):
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(400, "Invalid payment signature")


def captured_payment(credentials: dict, order_id: str, payment_id: str, amount: int):
    payment = provider_request("razorpay", "GET", "/payments/" + payment_id, credentials)
    if (payment.get("order_id") != order_id or payment.get("amount") != amount
            or payment.get("currency") != "INR" or payment.get("status") != "captured"):
        raise HTTPException(409, "Payment is not captured for this order and amount. Reconcile payment status before fulfillment.")
    return payment


def check_connection(provider: str, credentials: dict, pickup_location: str) -> str:
    if provider == "razorpay":
        response = provider_request("razorpay", "GET", "/orders?count=1", credentials)
        if response.get("entity") != "collection" or not isinstance(response.get("items"), list):
            raise HTTPException(502, "Razorpay returned an unexpected response. Check API access in your Razorpay dashboard.")
        return "Razorpay accepted the saved keys and allowed order access. This is not KYC approval, a payment test, webhook verification or confirmation of live settlement."
    login = provider_request("shiprocket", "POST", "/auth/login", {}, {
        "email": credentials["shiprocket_email"], "password": credentials["shiprocket_password"]})
    token = login.get("token")
    if not isinstance(token, str) or not token:
        raise HTTPException(502, "Shiprocket did not accept the saved API-user login. Use a dedicated API user, not your main dashboard password.")
    response = provider_request("shiprocket", "GET", "/settings/company/pickup", {"token": token})
    data = response.get("data")
    locations = data.get("shipping_address") if isinstance(data, dict) else None
    if not isinstance(locations, list):
        raise HTTPException(502, "Shiprocket returned an unexpected pickup-location response. Check API-user permissions.")
    if not any(isinstance(location, dict) and location.get("pickup_location") == pickup_location for location in locations):
        raise HTTPException(409, "Shiprocket login worked, but the saved pickup location was not found. Copy its exact name from Shiprocket, save and check again.")
    return "Shiprocket accepted the API-user login and the pickup location exists. This does not verify KYC, pickup approval, wallet balance or delivery serviceability. No shipment was created."
