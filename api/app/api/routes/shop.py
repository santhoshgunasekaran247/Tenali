import json
import re
import secrets
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.routes.auth import PasswordChange, administrator, identity_db
from app.core.database import SessionLocal, get_db
from app.schemas.checkout import CheckoutInput, CheckoutSettingsInput, PackageInput, PaymentConfirmation, ShipmentReconcile, ShopperRegistration
from app.services import checkout_providers as providers
from app.services.customer_security import SHOP_COOKIE, SHOP_CSRF, check_write, ensure_csrf, expiry, set_cookies, shopper_identity, storefront_company, verify_password
from app.services.shop_checkout import ORDER_COLUMNS, confirm_payment, create_order, create_shipment, price_item, reconcile_payment, reconcile_shipment, settings_for
from app.services.tenant_auth import TenantAuth
from app.services.tenant_context import company_by_slug, host_company, platform_host
from app.services.tenant_security import Login, password_hash, password_matches, token_digest

router = APIRouter()
admin_router = APIRouter()


def store(request: Request, db=Depends(identity_db)):
    check_write(request)
    return storefront_company(db, request)


def customer(request: Request, company=Depends(store), db=Depends(identity_db)):
    return shopper_identity(db, request, str(company["id"]))


def shop_db(company=Depends(store), identity=Depends(customer)):
    with SessionLocal() as db:
        db.info["tenant_context"] = {"company_id": str(company["id"]), "user_id": None}
        yield db


def new_session(db, request, response, company_id, account):
    token = secrets.token_urlsafe(48)
    db.execute(text("delete from shopper_sessions where expires_at<now()"))
    db.execute(text("insert into shopper_sessions(token_hash,company_id,shopper_id,expires_at) values(:token,:company,:shopper,:expires)"),
               {"token": token_digest(token), "company": company_id, "shopper": account["id"], "expires": expiry()})
    db.commit()
    set_cookies(response, request, token, SHOP_COOKIE, SHOP_CSRF)
    return {key: account[key] for key in ["id", "email", "display_name"]}


def throttle(db, request, company_id):
    TenantAuth(db).throttle("shop-auth:" + str(company_id) + ":" + (request.client.host if request.client else "unknown"), 20)


@router.post("/register", status_code=201)
def register(payload: ShopperRegistration, request: Request, response: Response, company=Depends(store), db=Depends(identity_db)):
    throttle(db, request, company["id"])
    try:
        account = db.execute(text("""insert into shopper_accounts(company_id,email,display_name,password_hash)
            values(:company,:email,:name,:hash) returning id,email,display_name"""),
            {"company": company["id"], "email": payload.email, "name": payload.display_name, "hash": password_hash(payload.password)}).mappings().one()
        return new_session(db, request, response, company["id"], account)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "A shopper account with this email already exists in this store") from error


@router.post("/login")
def login(payload: Login, request: Request, response: Response, company=Depends(store), db=Depends(identity_db)):
    throttle(db, request, company["id"])
    account = db.execute(text("select * from shopper_accounts where company_id=:company and email=:email"),
                         {"company": company["id"], "email": payload.email.strip().lower()}).mappings().first()
    verify_password(payload.password, account["password_hash"] if account and account["is_active"] else None)
    return new_session(db, request, response, company["id"], account)


@router.get("/session")
def session(request: Request, response: Response, identity=Depends(customer)):
    ensure_csrf(response, request, SHOP_CSRF)
    return identity


@router.post("/logout")
def logout(request: Request, response: Response, identity=Depends(customer), db=Depends(identity_db)):
    db.execute(text("delete from shopper_sessions where token_hash=:token"),
               {"token": token_digest(request.cookies.get(SHOP_COOKIE, ""))})
    db.commit()
    response.delete_cookie(SHOP_COOKIE, path="/")
    response.delete_cookie(SHOP_CSRF, path="/")
    return {"signed_out": True}


@router.post("/password")
def password(payload: PasswordChange, request: Request, company=Depends(store), identity=Depends(customer), db=Depends(identity_db)):
    throttle(db, request, company["id"])
    stored = db.execute(text("select password_hash from shopper_accounts where company_id=:company and id=:id for update"),
                        {"company": company["id"], "id": identity["id"]}).scalar_one()
    if not password_matches(payload.current_password, stored):
        raise HTTPException(422, "Current password is incorrect")
    db.execute(text("update shopper_accounts set password_hash=:hash where company_id=:company and id=:id"),
               {"hash": password_hash(payload.new_password), "company": company["id"], "id": identity["id"]})
    db.execute(text("delete from shopper_sessions where company_id=:company and shopper_id=:id and token_hash<>:current"),
               {"company": company["id"], "id": identity["id"], "current": token_digest(request.cookies.get(SHOP_COOKIE, ""))})
    db.commit()
    return {"changed": True}


@router.get("/availability")
def availability(company=Depends(store), db=Depends(identity_db)):
    settings = db.execute(text("select enabled,shipping_paise from checkout_settings where company_id=:company"),
                          {"company": company["id"]}).mappings().first()
    return {"enabled": bool(settings and settings["enabled"]), "shipping_paise": settings["shipping_paise"] if settings else None}


@router.post("/quote")
def quote(payload: CheckoutInput, company=Depends(store), identity=Depends(customer), db=Depends(shop_db), privileged=Depends(identity_db)):
    settings = settings_for(privileged, str(company["id"]))
    keys = [(str(item.product_id), str(item.variant_id or "")) for item in payload.items]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, "Combine duplicate cart entries into a single quantity")
    items = [price_item(db, str(company["id"]), item) for item in sorted(payload.items, key=lambda item: (str(item.product_id), str(item.variant_id or "")))]
    subtotal = sum(item["unit_paise"] * item["quantity"] for item in items)
    return {"items": items, "subtotal_paise": subtotal, "shipping_paise": settings["shipping_paise"], "total_paise": subtotal + settings["shipping_paise"]}


@router.post("/orders", status_code=201)
def checkout(payload: CheckoutInput, company=Depends(store), identity=Depends(customer), db=Depends(shop_db), privileged=Depends(identity_db)):
    TenantAuth(privileged).throttle("checkout:" + str(identity["id"]), 20)
    return create_order(db, privileged, str(company["id"]), str(identity["id"]), payload)


@router.get("/orders")
def orders(offset: int = Query(0, ge=0), company=Depends(store), identity=Depends(customer), db=Depends(shop_db)):
    return {"items": [dict(row) for row in db.execute(text(f"""select {ORDER_COLUMNS} from shop_orders
        where company_id=:company and shopper_id=:shopper order by created_at desc,id limit 50 offset :offset"""),
        {"company": company["id"], "shopper": identity["id"], "offset": offset}).mappings()]}


@router.post("/orders/{order_id}/confirm")
def confirm(order_id: UUID, payload: PaymentConfirmation, company=Depends(store), identity=Depends(customer), db=Depends(shop_db)):
    row = db.execute(text("select razorpay_order_id from shop_orders where company_id=:company and shopper_id=:shopper and id=:id"),
                     {"company": company["id"], "shopper": identity["id"], "id": order_id}).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Order not found")
    if row != payload.razorpay_order_id:
        raise HTTPException(400, "Payment does not belong to this order")
    return confirm_payment(db, str(company["id"]), str(order_id), payload.razorpay_payment_id, payload.razorpay_signature)


@router.post("/webhooks/razorpay/{slug}")
async def webhook(slug: str, request: Request, db=Depends(identity_db)):
    host = host_company(db, request)
    company = company_by_slug(db, slug)
    if not company or (host and str(host["id"]) != str(company["id"])) or (not host and not platform_host(request)):
        raise HTTPException(404, "Workspace not found")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 256_000:
            raise HTTPException(413, "Webhook payload too large")
    try:
        event = json.loads(body)
        payment = event["payload"]["payment"]["entity"]
        provider_order_id = payment["order_id"]
        payment_id = payment["id"]
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(400, "Invalid payment webhook") from error
    if (not isinstance(provider_order_id, str) or not re.fullmatch(r"order_[A-Za-z0-9]{1,94}", provider_order_id)
            or not isinstance(payment_id, str) or not re.fullmatch(r"pay_[A-Za-z0-9]{1,96}", payment_id)):
        raise HTTPException(400, "Invalid payment identifiers")
    row = db.execute(text("select id,credentials from shop_orders where company_id=:company and razorpay_order_id=:provider"),
                     {"company": company["id"], "provider": provider_order_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Order not found")
    credentials = providers.decrypt_credentials(str(company["id"]), row["credentials"])
    providers.verify_signature(credentials["razorpay_webhook_secret"], bytes(body), request.headers.get("X-Razorpay-Signature", ""))
    if event.get("event") != "payment.captured":
        return {"received": True}
    with SessionLocal() as scoped:
        scoped.info["tenant_context"] = {"company_id": str(company["id"]), "user_id": None}
        result = confirm_payment(scoped, str(company["id"]), str(row["id"]), payment_id)
    return {"received": True, "status": result["status"]}


@router.post("/orders/{order_id}/reconcile-payment")
def shopper_reconcile_payment(order_id: UUID, company=Depends(store), identity=Depends(customer), db=Depends(shop_db)):
    owned = db.execute(text("select id from shop_orders where company_id=:company and shopper_id=:shopper and id=:id"),
                       {"company": company["id"], "shopper": identity["id"], "id": order_id}).first()
    if not owned:
        raise HTTPException(404, "Order not found")
    return reconcile_payment(db, str(company["id"]), str(order_id))


@admin_router.get("/settings")
def read_settings(identity=Depends(administrator), db=Depends(identity_db)):
    settings = db.execute(text("select enabled,shipping_paise,pickup_location,credentials from checkout_settings where company_id=:company"),
                          {"company": identity["company_id"]}).mappings().first()
    if not settings:
        return {"configured": False, "payment_mode": None}
    credentials = providers.decrypt_credentials(str(identity["company_id"]), settings["credentials"])
    return {"configured": True, "enabled": settings["enabled"], "shipping_paise": settings["shipping_paise"],
            "pickup_location": settings["pickup_location"],
            "payment_mode": "test" if credentials["razorpay_key_id"].startswith("rzp_test_") else "live"}


@admin_router.put("/settings")
def save_settings(payload: CheckoutSettingsInput, identity=Depends(administrator), db=Depends(identity_db)):
    keys = ["razorpay_key_id", "razorpay_key_secret", "razorpay_webhook_secret", "shiprocket_email", "shiprocket_password"]
    for pair in [("razorpay_key_id", "razorpay_key_secret"), ("shiprocket_email", "shiprocket_password")]:
        if (getattr(payload, pair[0]) is None) != (getattr(payload, pair[1]) is None):
            raise HTTPException(422, "Replace both the Razorpay key ID and secret together, or both the Shiprocket email and password together.")
    stored = db.execute(text("select credentials from checkout_settings where company_id=:company for update"),
                        {"company": identity["company_id"]}).scalar_one_or_none()
    supplied = {key: getattr(payload, key).get_secret_value() if hasattr(getattr(payload, key), "get_secret_value")
                else getattr(payload, key) for key in keys if getattr(payload, key) is not None}
    credentials = {} if len(supplied) == len(keys) or not stored else providers.decrypt_credentials(str(identity["company_id"]), stored)
    credentials.update(supplied)
    if any(not credentials.get(key) for key in keys):
        raise HTTPException(422, "First-time setup requires the Razorpay key ID, key secret, webhook secret and Shiprocket API-user email and password.")
    encrypted = providers.encrypt_credentials(str(identity["company_id"]), credentials)
    db.execute(text("""insert into checkout_settings(company_id,enabled,shipping_paise,pickup_location,credentials)
        values(:company,:enabled,:shipping,:pickup,:credentials) on conflict(company_id) do update set
        enabled=excluded.enabled,shipping_paise=excluded.shipping_paise,pickup_location=excluded.pickup_location,
        credentials=excluded.credentials,updated_at=now()"""),
        {"company": identity["company_id"], "enabled": payload.enabled, "shipping": payload.shipping_paise,
         "pickup": payload.pickup_location, "credentials": encrypted})
    TenantAuth(db).audit(str(identity["company_id"]), str(identity["user_id"]), "CHECKOUT_SETTINGS_UPDATED",
                         details={"enabled": payload.enabled})
    db.commit()
    return {"saved": True}


@admin_router.post("/settings/check/{provider}")
def check_provider(provider: Literal["razorpay", "shiprocket"], identity=Depends(administrator), db=Depends(identity_db)):
    company_id = str(identity["company_id"])
    TenantAuth(db).throttle("checkout-check:" + company_id, 12)
    row = db.execute(text("select credentials,pickup_location from checkout_settings where company_id=:company"),
                     {"company": company_id}).mappings().first()
    if not row:
        raise HTTPException(409, "Save your setup before testing the provider connections.")
    try:
        credentials = providers.decrypt_credentials(company_id, row["credentials"])
        message = providers.check_connection(provider, credentials, row["pickup_location"])
    except HTTPException as error:
        if error.status_code not in {409, 502, 503}:
            raise
        return {"provider": provider, "status": "failed", "message": error.detail, "checked_at": datetime.now(timezone.utc)}
    return {"provider": provider, "status": "passed", "message": message, "checked_at": datetime.now(timezone.utc)}


@admin_router.get("/orders")
def staff_orders(offset: int = Query(0, ge=0), identity=Depends(administrator), db=Depends(get_db)):
    return {"items": [dict(row) for row in db.execute(text(f"""select {ORDER_COLUMNS} from shop_orders
        where company_id=:company order by created_at desc,id limit 50 offset :offset"""),
        {"company": identity["company_id"], "offset": offset}).mappings()]}


@admin_router.post("/orders/{order_id}/ship")
def ship(order_id: UUID, payload: PackageInput, identity=Depends(administrator), db=Depends(get_db), privileged=Depends(identity_db)):
    return create_shipment(db, privileged, str(identity["company_id"]), str(order_id), payload)


@admin_router.post("/orders/{order_id}/reconcile-shipment")
def reconcile(order_id: UUID, payload: ShipmentReconcile, identity=Depends(administrator), db=Depends(get_db)):
    return reconcile_shipment(db, str(identity["company_id"]), str(order_id), payload.provider_order_id)


@admin_router.post("/orders/{order_id}/reconcile-payment")
def staff_reconcile_payment(order_id: UUID, identity=Depends(administrator), db=Depends(get_db)):
    return reconcile_payment(db, str(identity["company_id"]), str(order_id))
