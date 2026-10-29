import hashlib
import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.services import checkout_providers as providers
from app.services.commerce_stock import book_stock
from app.services.inventory_pricing import resolve_catalog_price
from app.services.shop_stock import reserved_stock

logger = logging.getLogger(__name__)
ORDER_COLUMNS = """id,status,items,address,subtotal_paise,shipping_paise,total_paise,provider_key_id,
    razorpay_order_id,razorpay_payment_id,shiprocket_order_id,shipment_id,awb,courier,shipping_error,created_at,paid_at"""


def settings_for(db, company_id: str, require_enabled=True):
    row = db.execute(text("select * from checkout_settings where company_id=:company"), {"company": company_id}).mappings().first()
    if not row or (require_enabled and not row["enabled"]):
        raise HTTPException(409, "Online checkout is not enabled for this store")
    return dict(row)


def price_item(db, company_id: str, item):
    product_id = str(item.product_id)
    product = db.execute(text("""select * from products where id=:id and company_id=:company
        and is_active=true and catalog_visible=true for update"""),
        {"id": product_id, "company": company_id}).mappings().first()
    if not product:
        raise HTTPException(422, "Choose an active product from this store")
    if item.quantity < product["minimum_order_quantity"]:
        raise HTTPException(422, f"Minimum order for {product['name']} is {product['minimum_order_quantity']} units per size / colour.")
    variant = None
    if item.variant_id:
        variant = db.execute(text("select * from product_variants where id=:id and product_id=:product and is_active=true"),
                             {"id": item.variant_id, "product": product_id}).mappings().first()
        if not variant:
            raise HTTPException(422, "Choose a variant belonging to this product")
    elif db.execute(text("select 1 from product_variants where product_id=:product and is_active=true limit 1"),
                    {"product": product_id}).first():
        raise HTTPException(422, "Select a product variant before checkout")
    selected = variant if variant and variant["pricing_mode"] != "inherit" else product
    vendor_id = (variant["preferred_vendor_id"] if variant else None) or product["preferred_vendor_id"]
    mrp = variant["mrp"] if variant else product["mrp"]
    if vendor_id:
        mrp = db.execute(text("""select offer.mrp from vendor_contributions offer join parties vendor on vendor.id=offer.vendor_id
            where offer.product_id=:product and offer.variant_id is not distinct from cast(:variant as uuid)
            and offer.vendor_id=:vendor and offer.is_active=true and vendor.is_active=true and vendor.company_id=:company
            order by offer.created_at,offer.id limit 1"""),
            {"product": product_id, "variant": item.variant_id, "vendor": vendor_id, "company": company_id}).scalar_one_or_none()
    price = resolve_catalog_price(mrp, selected["selling_price"], selected["discount_percent"], selected["pricing_mode"])["catalog_price"]
    if price is None or price <= 0:
        raise HTTPException(422, "This item requires a quote and cannot be purchased online")
    paise = int((price * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    stock = db.execute(text("""select coalesce(sum(quantity),0) from stock_balances where company_id=:company
        and product_id=:product and variant_id is not distinct from cast(:variant as uuid)"""),
        {"company": company_id, "product": product_id, "variant": item.variant_id}).scalar_one()
    if stock - reserved_stock(db, company_id, product_id, str(item.variant_id) if item.variant_id else None) < item.quantity:
        raise HTTPException(409, "Not enough available stock for " + product["name"])
    return {"product_id": product_id, "variant_id": str(item.variant_id) if item.variant_id else None,
            "name": product["name"] + (f" - {variant['variant_name']}" if variant else ""),
            "sku": (variant["sku"] if variant else product["sku"]) or str(item.variant_id or item.product_id),
            "quantity": item.quantity, "unit_paise": paise}


def create_order(db, identity_db, company_id: str, shopper_id: str, payload):
    # Serialize retries for the same shopper as well as stock allocation across shoppers.
    db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": company_id + ":" + shopper_id})
    request_hash = hashlib.sha256(payload.model_dump_json(exclude={"request_key"}).encode()).hexdigest()
    existing = db.execute(text("select * from shop_orders where company_id=:company and shopper_id=:shopper and request_key=:key"),
                          {"company": company_id, "shopper": shopper_id, "key": payload.request_key}).mappings().first()
    if existing:
        if existing["request_hash"] != request_hash:
            raise HTTPException(409, "This checkout request was already used with different details")
        return public_order(existing)
    settings = settings_for(identity_db, company_id)
    keys = [(str(item.product_id), str(item.variant_id or "")) for item in payload.items]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, "Combine duplicate cart entries into a single quantity")
    items = [price_item(db, company_id, item) for item in sorted(payload.items, key=lambda item: (str(item.product_id), str(item.variant_id or "")))]
    subtotal = sum(item["unit_paise"] * item["quantity"] for item in items)
    total = subtotal + settings["shipping_paise"]
    if payload.expected_total_paise != total:
        raise HTTPException(409, "The order total changed. Refresh the quote before paying.")
    if total > 100_000_000:
        raise HTTPException(422, "Order total exceeds the online checkout limit")
    credentials = providers.decrypt_credentials(company_id, settings["credentials"])
    order_id = str(uuid4())
    provider_order = providers.provider_request("razorpay", "POST", "/orders", credentials,
        {"amount": total, "currency": "INR", "receipt": order_id, "notes": {"tenali_order_id": order_id}})
    if (not isinstance(provider_order.get("id"), str) or not provider_order["id"].startswith("order_")
            or provider_order.get("amount") != total or provider_order.get("currency") != "INR"):
        raise HTTPException(502, "Razorpay returned an invalid order")
    row = db.execute(text("""insert into shop_orders(id,company_id,shopper_id,request_key,request_hash,items,address,
        subtotal_paise,shipping_paise,total_paise,provider_key_id,credentials,pickup_location,razorpay_order_id)
        values(:id,:company,:shopper,:key,:hash,cast(:items as jsonb),cast(:address as jsonb),:subtotal,:shipping,:total,
        :key_id,:credentials,:pickup,:provider_id) returning *"""),
        {"id": order_id, "company": company_id, "shopper": shopper_id, "key": payload.request_key, "hash": request_hash,
         "items": json.dumps(items), "address": payload.address.model_dump_json(), "subtotal": subtotal,
         "shipping": settings["shipping_paise"], "total": total, "key_id": credentials["razorpay_key_id"],
         "credentials": settings["credentials"], "pickup": settings["pickup_location"], "provider_id": provider_order["id"]}).mappings().one()
    db.commit()
    identity_db.commit()
    return public_order(row)


def public_order(row):
    return {key: row[key] for key in [part.strip() for part in ORDER_COLUMNS.replace("\n", "").split(",")]}


def confirm_payment(db, company_id: str, order_id: str, payment_id: str, signature: str | None = None):
    row = db.execute(text("select * from shop_orders where company_id=:company and id=:id for update"),
                     {"company": company_id, "id": order_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Order not found")
    credentials = providers.decrypt_credentials(company_id, row["credentials"])
    if signature:
        providers.verify_signature(credentials["razorpay_key_secret"], (row["razorpay_order_id"] + "|" + payment_id).encode(), signature)
    providers.captured_payment(credentials, row["razorpay_order_id"], payment_id, row["total_paise"])
    if row["razorpay_payment_id"]:
        if row["razorpay_payment_id"] != payment_id:
            raise HTTPException(409, "Order already has a different payment; contact the store")
        return public_order(row)
    status = "paid"
    try:
        with db.begin_nested():
            book_stock(db, company_id, row["items"], "OUT", "shop_order", order_id)
    except HTTPException as error:
        if error.status_code != 422:
            raise
        logger.warning("Captured order %s requires stock review in company %s", order_id, company_id)
        status = "payment_review"
    result = db.execute(text("""update shop_orders set status=:status,razorpay_payment_id=:payment,paid_at=now()
        where company_id=:company and id=:id returning *"""),
        {"company": company_id, "id": order_id, "status": status, "payment": payment_id}).mappings().one()
    db.commit()
    return public_order(result)


def reconcile_payment(db, company_id: str, order_id: str):
    row = db.execute(text("select * from shop_orders where company_id=:company and id=:id"),
                     {"company": company_id, "id": order_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Order not found")
    if row["razorpay_payment_id"]:
        return public_order(row)
    credentials = providers.decrypt_credentials(company_id, row["credentials"])
    response = providers.provider_request("razorpay", "GET", "/orders/" + row["razorpay_order_id"] + "/payments", credentials)
    payments = response.get("items")
    if not isinstance(payments, list):
        raise HTTPException(502, "Razorpay returned an invalid payment list")
    captured = [payment for payment in payments if payment.get("status") == "captured"]
    if len(captured) != 1 or not isinstance(captured[0].get("id"), str):
        raise HTTPException(409, "No single captured payment was confirmed. Check Razorpay before paying again.")
    payment_id = captured[0]["id"]
    if not payment_id.startswith("pay_") or not payment_id[4:].isalnum():
        raise HTTPException(502, "Razorpay returned an invalid payment ID")
    return confirm_payment(db, company_id, order_id, payment_id)


def create_shipment(db, identity_db, company_id: str, order_id: str, package):
    row = db.execute(text("select * from shop_orders where company_id=:company and id=:id for update"),
                     {"company": company_id, "id": order_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Order not found")
    if row["status"] == "shipment_booked":
        return public_order(row)
    if row["status"] != "paid":
        raise HTTPException(409, "Only verified, paid orders can be submitted. Reconcile any pending shipment before retrying.")
    if row["provider_key_id"].startswith("rzp_test_"):
        raise HTTPException(409, "This is a Razorpay test payment. Test orders cannot create real Shiprocket shipments.")
    credentials = providers.decrypt_credentials(company_id, row["credentials"])
    shopper_email = identity_db.execute(text("select email from shopper_accounts where company_id=:company and id=:shopper"),
                                        {"company": company_id, "shopper": row["shopper_id"]}).scalar_one()
    address = row["address"]
    payload = {
        "order_id": str(row["id"]), "order_date": row["created_at"].strftime("%Y-%m-%d %H:%M"),
        "pickup_location": row["pickup_location"], "billing_customer_name": address["name"],
        "billing_last_name": "", "billing_address": address["address"], "billing_city": address["city"],
        "billing_pincode": address["pincode"], "billing_state": address["state"], "billing_country": "India",
        "billing_email": shopper_email, "billing_phone": address["phone"], "shipping_is_billing": True,
        "order_items": [{"name": item["name"], "sku": item["sku"], "units": item["quantity"],
                         "selling_price": item["unit_paise"] / 100} for item in row["items"]],
        "payment_method": "Prepaid", "sub_total": row["subtotal_paise"] / 100,
        "shipping_charges": row["shipping_paise"] / 100, **{key: float(value) for key, value in package.model_dump().items()},
    }
    token = providers.provider_request("shiprocket", "POST", "/auth/login", {}, {
        "email": credentials["shiprocket_email"], "password": credentials["shiprocket_password"]}).get("token")
    if not isinstance(token, str) or not token:
        raise HTTPException(502, "Shiprocket authentication failed")
    # Persist uncertainty before the external side effect; never automatically duplicate a shipment.
    db.execute(text("update shop_orders set status='shipping_pending',shipping_error=null where company_id=:company and id=:id"),
               {"company": company_id, "id": order_id})
    db.commit()
    try:
        shipment = providers.provider_request("shiprocket", "POST", "/orders/create/adhoc", {"token": token}, payload)
        if not shipment.get("order_id") or not shipment.get("shipment_id"):
            raise HTTPException(502, "Shiprocket did not confirm the shipment. Reconcile it before retrying.")
    except HTTPException:
        db.execute(text("update shop_orders set shipping_error='Provider response uncertain. Reconcile in Shiprocket using the Tenali order ID.' where company_id=:company and id=:id"),
                   {"company": company_id, "id": order_id})
        db.commit()
        raise
    result = db.execute(text("""update shop_orders set status='shipment_booked',shiprocket_order_id=:provider,
        shipment_id=:shipment,shipping_error=null where company_id=:company and id=:id returning *"""),
        {"company": company_id, "id": order_id, "provider": shipment["order_id"], "shipment": shipment["shipment_id"]}).mappings().one()
    db.commit()
    return public_order(result)


def reconcile_shipment(db, company_id: str, order_id: str, provider_order_id: int):
    row = db.execute(text("select * from shop_orders where company_id=:company and id=:id for update"),
                     {"company": company_id, "id": order_id}).mappings().first()
    if not row or row["status"] not in {"shipping_pending", "shipment_booked"}:
        raise HTTPException(409, "No shipment is pending reconciliation")
    credentials = providers.decrypt_credentials(company_id, row["credentials"])
    token = providers.provider_request("shiprocket", "POST", "/auth/login", {}, {
        "email": credentials["shiprocket_email"], "password": credentials["shiprocket_password"]}).get("token")
    if not isinstance(token, str) or not token:
        raise HTTPException(502, "Shiprocket authentication failed")
    remote = providers.provider_request("shiprocket", "GET", f"/orders/show/{provider_order_id}", {"token": token}).get("data", {})
    if str(remote.get("channel_order_id")) != str(row["id"]):
        raise HTTPException(409, "The Shiprocket order does not belong to this Tenali order")
    shipments = remote.get("shipments") or []
    shipment = shipments[0] if isinstance(shipments, list) and shipments else shipments
    if not isinstance(shipment, dict) or not shipment.get("id"):
        raise HTTPException(409, "Shiprocket has not confirmed a shipment")
    result = db.execute(text("""update shop_orders set status='shipment_booked',shiprocket_order_id=:provider,
        shipment_id=:shipment,awb=:awb,courier=:courier,shipping_error=null
        where company_id=:company and id=:id returning *"""),
        {"company": company_id, "id": order_id, "provider": provider_order_id, "shipment": shipment["id"],
         "awb": shipment.get("awb"), "courier": shipment.get("courier")}).mappings().one()
    db.commit()
    return public_order(result)
