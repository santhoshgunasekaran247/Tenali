import json
import re
import secrets
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.routes.auth import PasswordChange, administrator, identity_db
from app.core.database import SessionLocal, get_db
from app.schemas.checkout import (CheckoutInput, CheckoutSettingsInput, CodDecision, CodSettlementInput, CollectInput, DispatchInput,
                                  EnquiryInput, EnquiryUpdate, OrderCancel, PackageInput, PaymentConfirmation, ShipmentReconcile, ShopperRegistration)
from app.services import checkout_providers as providers
from app.services import shop_orders_service as orders_service
from app.services import shopper_federation as federation
from app.services.customer_contacts import normalize_phone
from app.services.federation_settings import public_config
from app.services.customer_security import SHOP_COOKIE, SHOP_CSRF, check_write, ensure_csrf, expiry, set_cookies, shopper_identity, storefront_company
from app.services.shop_checkout import ORDER_COLUMNS, confirm_payment, create_order, create_shipment, quote_order, reconcile_payment, reconcile_shipment, settings_for
from app.services.storefront_access import ensure_storefront_enabled
from app.services.tenant_auth import TenantAuth
from app.services.tenant_context import company_by_slug, host_company, platform_host
from app.services.tenant_security import Login, token_digest

router = APIRouter()
admin_router = APIRouter()


def store(request: Request, db=Depends(identity_db)):
    check_write(request)
    return storefront_company(db, request)


def open_store(company=Depends(store), db=Depends(identity_db)):
    ensure_storefront_enabled(db, company["id"])
    return company


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
    return {key: account[key] for key in ["id", "email", "display_name", "phone"]}


def throttle(db, request, company_id):
    TenantAuth(db).throttle("shop-auth:" + str(company_id) + ":" + (request.client.host if request.client else "unknown"), 20)


@router.post("/register", status_code=201)
def register(payload: ShopperRegistration, request: Request, response: Response, company=Depends(store), db=Depends(identity_db)):
    raise HTTPException(410, "Use federated shopper login. Email/password registration is no longer available.")


@router.post("/login")
def login(payload: Login, request: Request, response: Response, company=Depends(store), db=Depends(identity_db)):
    raise HTTPException(410, "Use federated shopper login. Email/password login is no longer available.")


class FederatedLogin(BaseModel):
    id_token: str = Field(min_length=1, max_length=10000, repr=False)
    phone: str | None = Field(default=None, max_length=40)
    display_name: str | None = Field(default=None, max_length=150)


@router.get("/auth-config")
def auth_config(company=Depends(store), db=Depends(identity_db)):
    return public_config(db)


@router.post("/federated")
def federated_login(payload: FederatedLogin, request: Request, response: Response, company=Depends(store), db=Depends(identity_db)):
    throttle(db, request, company["id"])
    identity = federation.verified_identity(payload.id_token, public_config(db))
    if not payload.phone:
        account = db.execute(text(f"""select {federation.ACCOUNT_COLUMNS} from shopper_accounts
            where company_id=:company and supabase_uid=:uid and is_active"""),
            {"company": company["id"], "uid": identity["uid"]}).mappings().first()
        if not account:
            return {"needs_profile": True, "email": identity["email"], "display_name": identity["name"]}
    try:
        account = federation.federated_account(db, str(company["id"]), identity, payload.phone, payload.display_name)
        return new_session(db, request, response, company["id"], account)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "This email is already associated with an account. Contact the store for identity review.") from error


@router.get("/session")
def session(request: Request, response: Response, identity=Depends(customer)):
    ensure_csrf(response, request, SHOP_CSRF)
    return identity


class ShopperProfile(BaseModel):
    display_name: str = Field(min_length=1, max_length=150)
    phone: str = Field(min_length=1, max_length=40)


@router.post("/profile")
def update_profile(payload: ShopperProfile, identity=Depends(customer), company=Depends(store), db=Depends(identity_db)):
    try:
        phone = normalize_phone(payload.phone, required=True)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    name = payload.display_name.strip()
    if not name:
        raise HTTPException(422, "Enter your name")
    row = db.execute(text("""update shopper_accounts set phone=:phone,display_name=:name
        where company_id=:company and id=:id returning id,email,display_name,phone"""),
        {"company": company["id"], "id": identity["id"], "phone": phone, "name": name}).mappings().one()
    db.commit()
    return dict(row)


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
    raise HTTPException(410, "Manage your password with your social login provider.")


def public_db(company=Depends(store)):
    with SessionLocal() as db:
        db.info["tenant_context"] = {"company_id": str(company["id"]), "user_id": None}
        yield db


@router.get("/availability")
def availability(company=Depends(open_store), db=Depends(identity_db)):
    settings = db.execute(text("""select enabled,shipping_paise,prepaid_enabled,cod_enabled,cod_limit,pickup_enabled
        from checkout_settings where company_id=:company"""), {"company": company["id"]}).mappings().first()
    pickup_stores = [dict(row) for row in db.execute(text("""select id,code,name,address,pincode,whatsapp_number from stores
        where company_id=:company and is_active and holds_stock and allows_pickup order by name"""), {"company": company["id"]}).mappings()]
    online = db.execute(text("select 1 from stores where company_id=:company and kind='online' and is_active"), {"company": company["id"]}).first()
    whatsapp = orders_service.whatsapp_number(db, str(company["id"]), None)
    return {"enabled": bool(settings and settings["enabled"] and online), "shipping_paise": settings["shipping_paise"] if settings else None,
            "prepaid_enabled": bool(settings and settings["prepaid_enabled"]), "cod_enabled": bool(settings and settings["cod_enabled"]),
            "cod_limit": float(settings["cod_limit"]) if settings else None, "pickup_enabled": bool(settings and settings["pickup_enabled"]),
            "pickup_stores": pickup_stores, "whatsapp_number": whatsapp}


@router.get("/nearby")
def nearby(product_id: UUID, variant_id: UUID | None = None, lat: float | None = Query(None, ge=-90, le=90),
           lng: float | None = Query(None, ge=-180, le=180), pincode: str | None = Query(None, pattern=r"^[1-9][0-9]{5}$"),
           request: Request = None, company=Depends(open_store), db=Depends(public_db), privileged=Depends(identity_db)):
    throttle(privileged, request, company["id"])
    return orders_service.nearby_availability(db, str(company["id"]), str(product_id), str(variant_id) if variant_id else None, lat, lng, pincode)


@router.post("/enquiries", status_code=201)
def enquire(payload: EnquiryInput, request: Request, company=Depends(open_store), db=Depends(public_db), privileged=Depends(identity_db)):
    throttle(privileged, request, company["id"])
    return orders_service.create_enquiry(db, str(company["id"]), payload)


@router.post("/quote")
def quote(payload: CheckoutInput, company=Depends(open_store), identity=Depends(customer), db=Depends(shop_db), privileged=Depends(identity_db)):
    settings = settings_for(privileged, str(company["id"]))
    result = quote_order(db, settings, str(company["id"]), payload)
    db.rollback()
    return {"items": result["items"], "subtotal_paise": result["subtotal_paise"], "shipping_paise": result["shipping_paise"],
            "total_paise": result["total_paise"], "pickup_store": result["pickup"]["name"] if result["pickup"] else None}


@router.post("/orders", status_code=201)
def checkout(payload: CheckoutInput, company=Depends(open_store), identity=Depends(customer), db=Depends(shop_db), privileged=Depends(identity_db)):
    TenantAuth(privileged).throttle("checkout:" + str(identity["id"]), 20)
    return create_order(db, privileged, str(company["id"]), str(identity["id"]), payload)


@router.get("/orders")
def orders(offset: int = Query(0, ge=0), company=Depends(store), identity=Depends(customer), db=Depends(shop_db)):
    orders_service.expire_orders(db, str(company["id"]))
    db.commit()
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


POLICY_FIELDS = ["prepaid_enabled", "shipping_sac", "shipping_gst_rate", "cod_enabled", "cod_limit", "cod_approval_hours", "cod_overdue_days",
                 "cod_serviceable_pincodes", "pickup_enabled", "pickup_hold_hours", "pickup_reminder_hours", "prepaid_hold_minutes"]


@admin_router.get("/settings")
def read_settings(identity=Depends(administrator), db=Depends(identity_db)):
    settings = db.execute(text("select * from checkout_settings where company_id=:company"),
                          {"company": identity["company_id"]}).mappings().first()
    if not settings:
        return {"configured": False, "payment_mode": None}
    payment_mode = None
    if settings["credentials"]:
        credentials = providers.decrypt_credentials(str(identity["company_id"]), settings["credentials"])
        payment_mode = "test" if credentials.get("razorpay_key_id", "").startswith("rzp_test_") else "live"
    return {"configured": True, "enabled": settings["enabled"], "shipping_paise": settings["shipping_paise"],
            "pickup_location": settings["pickup_location"], "payment_mode": payment_mode, "credentials_saved": bool(settings["credentials"]),
            **{field: settings[field] for field in POLICY_FIELDS}}


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
    if payload.prepaid_enabled and any(not credentials.get(key) for key in keys):
        raise HTTPException(422, "Online payment requires the Razorpay key ID, key secret, webhook secret and Shiprocket API-user email and password; or disable online payment to run cash-on-delivery and pickup only.")
    if payload.enabled and not (payload.prepaid_enabled or payload.cod_enabled or payload.pickup_enabled):
        raise HTTPException(422, "Enable at least one of online payment, cash on delivery or store pickup")
    encrypted = providers.encrypt_credentials(str(identity["company_id"]), credentials) if credentials else ""
    policy = {field: getattr(payload, field) for field in POLICY_FIELDS}
    db.execute(text("""insert into checkout_settings(company_id,enabled,shipping_paise,pickup_location,credentials,
            prepaid_enabled,shipping_sac,shipping_gst_rate,cod_enabled,cod_limit,cod_approval_hours,cod_overdue_days,cod_serviceable_pincodes,
            pickup_enabled,pickup_hold_hours,pickup_reminder_hours,prepaid_hold_minutes)
        values(:company,:enabled,:shipping,:pickup,:credentials,:prepaid_enabled,:shipping_sac,:shipping_gst_rate,:cod_enabled,:cod_limit,
            :cod_approval_hours,:cod_overdue_days,:cod_serviceable_pincodes,:pickup_enabled,:pickup_hold_hours,:pickup_reminder_hours,:prepaid_hold_minutes)
        on conflict(company_id) do update set
        enabled=excluded.enabled,shipping_paise=excluded.shipping_paise,pickup_location=excluded.pickup_location,
        credentials=excluded.credentials,prepaid_enabled=excluded.prepaid_enabled,shipping_sac=excluded.shipping_sac,
        shipping_gst_rate=excluded.shipping_gst_rate,cod_enabled=excluded.cod_enabled,cod_limit=excluded.cod_limit,
        cod_approval_hours=excluded.cod_approval_hours,cod_overdue_days=excluded.cod_overdue_days,
        cod_serviceable_pincodes=excluded.cod_serviceable_pincodes,pickup_enabled=excluded.pickup_enabled,
        pickup_hold_hours=excluded.pickup_hold_hours,pickup_reminder_hours=excluded.pickup_reminder_hours,
        prepaid_hold_minutes=excluded.prepaid_hold_minutes,updated_at=now()"""),
        {"company": identity["company_id"], "enabled": payload.enabled, "shipping": payload.shipping_paise,
         "pickup": payload.pickup_location, "credentials": encrypted, **policy})
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
def staff_orders(offset: int = Query(0, ge=0), status: str | None = None, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.staff_orders(db, str(identity["company_id"]), offset, status)


@admin_router.post("/orders/{order_id}/approve-cod")
def approve_cod(order_id: UUID, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.approve_cod(db, str(identity["company_id"]), str(order_id))


@admin_router.post("/orders/{order_id}/decline-cod")
def decline_cod(order_id: UUID, payload: CodDecision, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.decline_cod(db, str(identity["company_id"]), str(order_id), payload.reason)


@admin_router.post("/orders/{order_id}/dispatch")
def dispatch(order_id: UUID, payload: DispatchInput, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.dispatch_order(db, str(identity["company_id"]), str(order_id), payload)


@admin_router.post("/orders/{order_id}/ready")
def ready_for_pickup(order_id: UUID, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.mark_ready_for_pickup(db, str(identity["company_id"]), str(order_id))


@admin_router.post("/orders/{order_id}/collect")
def collect(order_id: UUID, payload: CollectInput, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.collect_pickup(db, str(identity["company_id"]), str(order_id), payload)


@admin_router.post("/orders/{order_id}/delivered")
def delivered(order_id: UUID, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.mark_delivered(db, str(identity["company_id"]), str(order_id))


@admin_router.post("/orders/{order_id}/cancel")
def cancel(order_id: UUID, payload: OrderCancel, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.cancel_order(db, str(identity["company_id"]), str(order_id), payload)


@admin_router.post("/orders/{order_id}/post-advance")
def post_advance(order_id: UUID, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.retry_advance(db, str(identity["company_id"]), str(order_id))


@admin_router.get("/cod")
def cod_outstanding(identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.cod_outstanding(db, str(identity["company_id"]))


@admin_router.post("/cod/settlements", status_code=201)
def cod_settlement(payload: CodSettlementInput, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.record_cod_settlement(db, str(identity["company_id"]), payload)


@admin_router.get("/enquiries")
def enquiries(status: str | None = None, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.list_enquiries(db, str(identity["company_id"]), status)


@admin_router.put("/enquiries/{enquiry_id}")
def update_enquiry(enquiry_id: UUID, payload: EnquiryUpdate, identity=Depends(administrator), db=Depends(get_db)):
    return orders_service.update_enquiry(db, str(identity["company_id"]), str(enquiry_id), payload)


@admin_router.post("/orders/{order_id}/ship")
def ship(order_id: UUID, payload: PackageInput, identity=Depends(administrator), db=Depends(get_db), privileged=Depends(identity_db)):
    return create_shipment(db, privileged, str(identity["company_id"]), str(order_id), payload)


@admin_router.post("/orders/{order_id}/reconcile-shipment")
def reconcile(order_id: UUID, payload: ShipmentReconcile, identity=Depends(administrator), db=Depends(get_db)):
    return reconcile_shipment(db, str(identity["company_id"]), str(order_id), payload.provider_order_id)


@admin_router.post("/orders/{order_id}/reconcile-payment")
def staff_reconcile_payment(order_id: UUID, identity=Depends(administrator), db=Depends(get_db)):
    return reconcile_payment(db, str(identity["company_id"]), str(order_id))
