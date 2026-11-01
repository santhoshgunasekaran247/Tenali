"""Online order lifecycle: advances, COD approval, dispatch/pickup invoicing, settlements, expiry, enquiries."""

from __future__ import annotations

import math
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.billing import InvoiceCreate, InvoiceLineCreate
from app.schemas.checkout import CodSettlementInput, CollectInput, DispatchInput, EnquiryInput, EnquiryUpdate, OrderCancel
from app.schemas.masters import HsnMasterCreate
from app.services.collection_ledger import lock_invoice_receivables, sync_receivable
from app.services.gst_states import place_of_supply, place_of_supply_for_code
from app.services.period_lock_service import assert_period_open
from app.services.shop_checkout import ORDER_COLUMNS, checkout_policy, public_order
from app.services.stores_service import get_store, stock_store

ONLINE_PARTY_SQL = "select id from parties where company_id=:company and system_role='online_shopper' and is_active"


def _order(db: Session, company_id: str, order_id: str, lock: bool = True) -> dict:
    row = db.execute(text(f"select * from shop_orders where company_id=:company and id=:id {'for update' if lock else ''}"),
                     {"company": company_id, "id": order_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Order not found")
    return dict(row)


def _actor(db: Session) -> str | None:
    return (db.info.get("tenant_context") or {}).get("user_id")


def _order_out(db: Session, company_id: str, order_id: str) -> dict:
    return public_order(_order(db, company_id, order_id, lock=False))


def expire_orders(db: Session, company_id: str) -> int:
    """Release holds whose window has passed; the caller commits."""
    return db.execute(text("""update shop_orders set status='expired'
        where company_id=:company and expires_at is not null and expires_at<now()
        and status in ('awaiting_payment','cod_requested','confirmed')"""), {"company": company_id}).rowcount


def post_prepaid_advance(db: Session, company_id: str, order: dict) -> None:
    """Record a captured Razorpay payment as a customer advance in the online store's clearing account."""
    store = get_store(db, company_id, str(order["store_id"]))
    if not store["settlement_account_id"]:
        db.execute(text("update shop_orders set review_reason=:reason where id=:id"),
                   {"id": order["id"], "reason": "Advance not posted: set a settlement (Razorpay clearing) account on the online store"})
        return
    try:
        assert_period_open(db, company_id, date.today(), "Posting online payment")
    except HTTPException as error:
        db.execute(text("update shop_orders set review_reason=:reason where id=:id"),
                   {"id": order["id"], "reason": f"Advance not posted: {error.detail}"})
        return
    transaction = db.execute(text("""insert into account_transactions(company_id,store_id,from_account_id,to_account_id,amount,
            payment_mode,reference,category,description,transaction_date,source_type,source_id,created_by)
        values(:company,:store,null,:account,:amount,'online',:reference,'online_advance',:description,current_date,
            'shop_order',:order,cast(:actor as uuid)) returning id"""),
        {"company": company_id, "store": str(store["id"]), "account": str(store["settlement_account_id"]),
         "amount": Decimal(order["total_paise"]) / 100, "reference": order["razorpay_payment_id"],
         "description": f"Online order advance {str(order['id'])[:8]}", "order": str(order["id"]), "actor": _actor(db)}).scalar_one()
    db.execute(text("update shop_orders set advance_transaction_id=:tx, review_reason=null where id=:id"),
               {"tx": str(transaction), "id": order["id"]})


def retry_advance(db: Session, company_id: str, order_id: str) -> dict:
    order = _order(db, company_id, order_id)
    if order["payment_method"] != "prepaid" or not order["razorpay_payment_id"] or order["advance_transaction_id"]:
        raise HTTPException(409, "No pending advance to post for this order")
    post_prepaid_advance(db, company_id, order)
    db.commit()
    return _order_out(db, company_id, order_id)


def approve_cod(db: Session, company_id: str, order_id: str) -> dict:
    order = _order(db, company_id, order_id)
    if order["status"] != "cod_requested":
        raise HTTPException(409, "Only requested cash-on-delivery orders can be approved")
    from app.services.inventory_service import InventoryService
    inventory = InventoryService(db, company_id)
    warehouse = str(get_store(db, company_id, str(order["store_id"]))["fulfilment_store_id"])
    for item in order["items"]:
        available = inventory.available_stock(warehouse, item["product_id"], item["variant_id"], str(order["id"]))
        if available < Decimal(str(item["quantity"])):
            raise HTTPException(409, f"Only {available} of {item['name']} available at the warehouse; transfer stock or decline")
    db.execute(text("""update shop_orders set status='confirmed',approved_by=cast(:actor as uuid),approved_at=now(),expires_at=null
        where id=:id"""), {"id": order_id, "actor": _actor(db)})
    db.commit()
    return _order_out(db, company_id, order_id)


def decline_cod(db: Session, company_id: str, order_id: str, reason: str | None) -> dict:
    order = _order(db, company_id, order_id)
    if order["status"] != "cod_requested":
        raise HTTPException(409, "Only requested cash-on-delivery orders can be declined")
    db.execute(text("""update shop_orders set status='cancelled',cancelled_at=now(),decline_reason=:reason,
        cancellation_reason=:reason,expires_at=null where id=:id"""), {"id": order_id, "reason": reason or "Declined by store"})
    db.commit()
    return _order_out(db, company_id, order_id)


def _ensure_shipping_sac(db: Session, company_id: str, settings: dict) -> None:
    from app.services.masters_service import MastersService
    exists = db.execute(text("select id from hsn_masters where company_id=:company and code=:code"),
                        {"company": company_id, "code": settings["shipping_sac"]}).scalar_one_or_none()
    if not exists:
        MastersService(db).create_hsn(HsnMasterCreate(code=settings["shipping_sac"], description="Shipping and delivery charges",
                                                      gst_rate=settings["shipping_gst_rate"]), company_id)


def _invoice_lines(order: dict, settings: dict) -> list[InvoiceLineCreate]:
    lines = [InvoiceLineCreate(product_id=item["product_id"], variant_id=item["variant_id"], description=item["name"],
                               hsn=item.get("hsn") or "9999", quantity=item["quantity"],
                               rate=Decimal(item["unit_paise"]) / 100, price_includes_gst=True)
             for item in order["items"]]
    if order["shipping_paise"]:
        lines.append(InvoiceLineCreate(description="Shipping and delivery", hsn=settings["shipping_sac"], quantity=1,
                                       rate=Decimal(order["shipping_paise"]) / 100, price_includes_gst=True))
    return lines


def _address_text(address: dict) -> str:
    return ", ".join(str(address.get(key)) for key in ("address", "city", "state", "pincode") if address.get(key))


def _review(db: Session, company_id: str, order_id: str, reason: str):
    db.rollback()
    db.execute(text("update shop_orders set status='fulfilment_review',review_reason=:reason where company_id=:company and id=:id"),
               {"company": company_id, "id": order_id, "reason": reason})
    db.commit()
    raise HTTPException(409, f"Order moved to review: {reason}")


def _create_order_invoice(db: Session, company_id: str, order: dict, *, invoice_store: dict, stock_store_id: str,
                          supply: str, amount_received: Decimal, account_id: str | None, payment_mode: str | None,
                          reference: str) -> dict:
    from app.services.billing_service import BillingService
    settings = checkout_policy(db, company_id)
    _ensure_shipping_sac(db, company_id, settings)
    party = db.execute(text(ONLINE_PARTY_SQL), {"company": company_id}).scalar_one_or_none()
    if not party:
        raise HTTPException(409, "The 'Online shopper' customer party is missing; run the stores migration")
    address = order["address"]
    payload = InvoiceCreate(
        store_id=invoice_store["id"], stock_store_id=stock_store_id, customer_party_id=party,
        invoice_date=date.today(), amount_received=amount_received, account_id=account_id, payment_mode=payment_mode,
        reference=reference, notes=f"Online order {order['id']} ({order['payment_method']}, {order['fulfilment_method']})",
        lines=_invoice_lines(order, settings), billing_address=_address_text(address) or "Online order",
        shipping_name=address.get("name"), shipping_address=_address_text(address) or None, place_of_supply=supply,
        idempotency_key=f"shop-order:{order['id']}",
    )
    return BillingService(db).create_invoice(company_id, payload)


def dispatch_order(db: Session, company_id: str, order_id: str, payload: DispatchInput) -> dict:
    """Goods leave the warehouse (or the ship-from store staff choose): book stock and create the invoice."""
    order = _order(db, company_id, order_id)
    if order["invoice_id"]:
        return _order_out(db, company_id, order_id)
    allowed = {"paid", "shipment_booked", "shipping_pending"} if order["payment_method"] == "prepaid" else {"confirmed", "shipment_booked", "shipping_pending"}
    allowed.add("dispatched")  # retry after a partial dispatch whose invoice link did not complete
    if order["status"] not in allowed or order["payment_method"] == "pay_at_pickup":
        raise HTTPException(409, f"An order in status {order['status']} cannot be dispatched")
    if order["payment_method"] == "prepaid" and not order["advance_transaction_id"]:
        raise HTTPException(409, order["review_reason"] or "Post the online payment advance before dispatching")
    online = get_store(db, company_id, str(order["store_id"]))
    ship_from = stock_store(db, company_id, str(payload.ship_from_store_id) if payload.ship_from_store_id else str(online["fulfilment_store_id"]))
    if order["fulfilment_method"] == "pickup":
        pickup = get_store(db, company_id, str(order["pickup_store_id"]))
        supply = place_of_supply_for_code(pickup["state_code"]) or place_of_supply_for_code((pickup["gst_number"] or online["gst_number"] or "")[:2])
    else:
        supply = place_of_supply(order["address"].get("state"))
    if not supply:
        _review(db, company_id, order_id, "Place of supply could not be determined from the address; correct the state and retry")
    try:
        # Leave the stock-holding statuses first so the order's own reservation does not block its booking;
        # create_invoice commits, so a later failure is recoverable by re-running dispatch.
        db.execute(text("update shop_orders set status='dispatched',ship_from_store_id=:store,dispatched_at=coalesce(dispatched_at,now()) where id=:id"),
                   {"store": str(ship_from["id"]), "id": order_id})
        invoice = _create_order_invoice(db, company_id, order, invoice_store=online, stock_store_id=str(ship_from["id"]), supply=supply,
                                        amount_received=Decimal("0"), account_id=None, payment_mode=None,
                                        reference=f"Online order {str(order['id'])[:8]}")
        invoice_id = str(invoice["id"])
        if order["payment_method"] == "prepaid":
            # Attach the captured advance to the invoice as its receipt; no second inflow is posted.
            db.execute(text("""update account_transactions set source_type='invoice',source_id=:invoice,category='business_billing',
                reference=:number,description=:description where id=:tx and company_id=:company"""),
                {"invoice": invoice_id, "number": invoice["invoice_number"], "description": f"Online payment for {invoice['invoice_number']}",
                 "tx": str(order["advance_transaction_id"]), "company": company_id})
            db.execute(text("update invoices set payment_mode='online',account_id=(select to_account_id from account_transactions where id=:tx) where id=:invoice"),
                       {"tx": str(order["advance_transaction_id"]), "invoice": invoice_id})
            locked_invoice, receivable = lock_invoice_receivables(db, company_id, invoice_id)
            if receivable:
                sync_receivable(db, company_id, receivable, locked_invoice)
        db.execute(text("update shop_orders set invoice_id=:invoice,review_reason=null where id=:id"), {"invoice": invoice_id, "id": order_id})
        db.commit()
    except HTTPException as error:
        if error.status_code in {409, 422}:
            _review(db, company_id, order_id, str(error.detail))
        raise
    return _order_out(db, company_id, order_id)


def mark_ready_for_pickup(db: Session, company_id: str, order_id: str) -> dict:
    order = _order(db, company_id, order_id)
    if order["fulfilment_method"] != "pickup":
        raise HTTPException(409, "Only pickup orders can be marked ready")
    if order["payment_method"] == "prepaid" and order["status"] != "dispatched":
        raise HTTPException(409, "Dispatch the prepaid pickup order from the warehouse first")
    if order["payment_method"] == "pay_at_pickup" and order["status"] != "confirmed":
        raise HTTPException(409, "Only confirmed pickup orders can be marked ready")
    db.execute(text("update shop_orders set status='ready_for_pickup',ready_at=now() where id=:id"), {"id": order_id})
    db.commit()
    return _order_out(db, company_id, order_id)


def collect_pickup(db: Session, company_id: str, order_id: str, payload: CollectInput) -> dict:
    """Hand over at the shop. Pay-at-pickup creates the shop's invoice now; prepaid pickup only closes the order."""
    order = _order(db, company_id, order_id)
    retrying = order["status"] == "collected" and not order["invoice_id"] and order["payment_method"] == "pay_at_pickup"
    if order["fulfilment_method"] != "pickup" or (order["status"] not in {"confirmed", "ready_for_pickup", "dispatched"} and not retrying):
        raise HTTPException(409, "This order is not awaiting collection")
    if order["payment_method"] == "prepaid":
        if not order["invoice_id"]:
            raise HTTPException(409, "Dispatch the prepaid pickup order from the warehouse before handing it over")
        db.execute(text("update shop_orders set status='collected',collected_at=now() where id=:id"), {"id": order_id})
        db.commit()
        return _order_out(db, company_id, order_id)
    if not payload.account_id or not payload.payment_mode:
        raise HTTPException(422, "Record the account and payment mode used at the counter")
    shop = stock_store(db, company_id, str(order["pickup_store_id"]))
    supply = place_of_supply_for_code(shop["state_code"]) or place_of_supply_for_code((shop["gst_number"] or "")[:2])
    if not supply:
        company_gst = db.execute(text("select gst_number from companies where id=:id"), {"id": company_id}).scalar_one() or ""
        supply = place_of_supply_for_code(company_gst[:2])
    if not supply:
        raise HTTPException(409, "Set the shop's state code before invoicing pickups")
    try:
        db.execute(text("""update shop_orders set status='collected',ship_from_store_id=:store,collected_at=coalesce(collected_at,now())
            where id=:id"""), {"store": str(shop["id"]), "id": order_id})
        invoice = _create_order_invoice(db, company_id, order, invoice_store=shop, stock_store_id=str(shop["id"]), supply=supply,
                                        amount_received=Decimal(order["total_paise"]) / 100, account_id=str(payload.account_id),
                                        payment_mode=payload.payment_mode, reference=f"Pickup order {str(order['id'])[:8]}")
        db.execute(text("update shop_orders set invoice_id=:invoice,review_reason=null where id=:id"), {"invoice": str(invoice["id"]), "id": order_id})
        db.commit()
    except HTTPException as error:
        if error.status_code in {409, 422}:
            _review(db, company_id, order_id, str(error.detail))
        raise
    return _order_out(db, company_id, order_id)


def mark_delivered(db: Session, company_id: str, order_id: str) -> dict:
    order = _order(db, company_id, order_id)
    if order["fulfilment_method"] != "delivery" or order["status"] != "dispatched":
        raise HTTPException(409, "Only dispatched delivery orders can be marked delivered")
    db.execute(text("update shop_orders set status='delivered',delivered_at=now() where id=:id"), {"id": order_id})
    db.commit()
    return _order_out(db, company_id, order_id)


def cancel_order(db: Session, company_id: str, order_id: str, payload: OrderCancel) -> dict:
    order = _order(db, company_id, order_id)
    if order["invoice_id"]:
        raise HTTPException(409, "This order is invoiced; reverse its receipt and cancel the invoice from Billing instead")
    if order["status"] in {"cancelled", "refunded"}:
        return _order_out(db, company_id, order_id)
    status = "cancelled"
    if order["advance_transaction_id"]:
        if not payload.refund_account_id:
            raise HTTPException(422, "Choose the account the refund is paid from (normally the Razorpay clearing account)")
        assert_period_open(db, company_id, date.today(), "Refunding online order")
        db.execute(text("""insert into account_transactions(company_id,store_id,from_account_id,to_account_id,amount,payment_mode,
                reference,category,description,transaction_date,source_type,source_id,created_by)
            values(:company,:store,:account,null,:amount,'online',:reference,'online_refund',:description,current_date,
                'shop_order_refund',:order,cast(:actor as uuid))"""),
            {"company": company_id, "store": str(order["store_id"]), "account": str(payload.refund_account_id),
             "amount": Decimal(order["total_paise"]) / 100, "reference": order["razorpay_payment_id"],
             "description": f"Refund of online order {str(order['id'])[:8]}: {payload.reason}", "order": order_id, "actor": _actor(db)})
        status = "refunded"
    db.execute(text("""update shop_orders set status=:status,cancelled_at=now(),cancellation_reason=:reason,expires_at=null where id=:id"""),
               {"status": status, "reason": payload.reason, "id": order_id})
    db.commit()
    return _order_out(db, company_id, order_id)


def record_cod_settlement(db: Session, company_id: str, payload: CodSettlementInput) -> dict:
    """Post a courier remittance as one collection per COD invoice, atomically with the settlement record."""
    from app.services.collection_ledger import lock_receivable, receipt_totals
    account = db.execute(text("select id from accounts where id=:id and company_id=:company and is_active"),
                         {"id": str(payload.account_id), "company": company_id}).scalar_one_or_none()
    if not account:
        raise HTTPException(422, "Choose an active settlement account")
    assert_period_open(db, company_id, payload.settlement_date, "Recording COD settlement")
    if db.execute(text("select 1 from cod_settlements where company_id=:company and courier=:courier and settlement_reference=:reference"),
                  {"company": company_id, "courier": payload.courier, "reference": payload.settlement_reference}).first():
        raise HTTPException(409, "This settlement reference has already been recorded for the courier")
    expected = Decimal("0")
    received = sum((item.amount for item in payload.items), Decimal("0"))
    postings = []
    for item in payload.items:
        order = _order(db, company_id, str(item.order_id))
        if order["payment_method"] != "cod" or not order["invoice_id"]:
            raise HTTPException(422, f"Order {str(item.order_id)[:8]} is not a dispatched cash-on-delivery order")
        receivable_id = db.execute(text("select id from receivables where company_id=:company and invoice_id=:invoice"),
                                   {"company": company_id, "invoice": str(order["invoice_id"])}).scalar_one_or_none()
        if not receivable_id:
            raise HTTPException(409, f"Order {str(item.order_id)[:8]} has no receivable to settle")
        receivable, invoice = lock_receivable(db, company_id, str(receivable_id))
        if receivable["status"] == "BAD_DEBT":
            raise HTTPException(422, f"Order {str(item.order_id)[:8]} is written off; revert its status before settling")
        current, _ = receipt_totals(db, company_id, receivable, invoice)
        outstanding = Decimal(receivable["amount_due"]) - current
        expected += outstanding
        if item.amount > outstanding:
            raise HTTPException(422, f"Order {str(item.order_id)[:8]}: {item.amount} exceeds the outstanding {outstanding}")
        if invoice and payload.settlement_date < invoice["invoice_date"]:
            raise HTTPException(422, f"Order {str(item.order_id)[:8]}: settlement date precedes the invoice date")
        postings.append((order, receivable, invoice, item.amount))
    if received < expected and not payload.shortfall_reason:
        raise HTTPException(422, f"Received {received} is below the expected {expected}; give a shortfall reason (courier fee, bad debt, ...)")
    settlement = db.execute(text("""insert into cod_settlements(company_id,courier,settlement_reference,settlement_date,account_id,
            expected_amount,received_amount,shortfall_reason,notes,created_by)
        values(:company,:courier,:reference,:date,:account,:expected,:received,:shortfall,:notes,cast(:actor as uuid)) returning id"""),
        {"company": company_id, "courier": payload.courier, "reference": payload.settlement_reference, "date": payload.settlement_date,
         "account": str(payload.account_id), "expected": expected, "received": received,
         "shortfall": payload.shortfall_reason if received < expected else None, "notes": payload.notes, "actor": _actor(db)}).scalar_one()
    for order, receivable, invoice, amount in postings:
        payment = db.execute(text("""insert into receivable_payments(receivable_id,company_id,account_id,amount,payment_mode,idempotency_key,
                reference,payment_date,notes)
            values(:receivable,:company,:account,:amount,'cod_remittance',:key,:reference,:date,:notes) returning id"""),
            {"receivable": receivable["id"], "company": company_id, "account": str(payload.account_id), "amount": amount,
             "key": f"cod:{payload.courier}:{payload.settlement_reference}:{order['id']}", "reference": payload.settlement_reference,
             "date": payload.settlement_date, "notes": f"COD remittance {payload.settlement_reference} ({payload.courier})"}).scalar_one()
        db.execute(text("""insert into account_transactions(company_id,from_account_id,to_account_id,amount,payment_mode,reference,category,
                description,transaction_date,source_type,source_id,created_by)
            values(:company,null,:account,:amount,'cod_remittance',:reference,'sales_collection',:description,:date,'receivable_payment',:payment,
                cast(:actor as uuid))"""),
            {"company": company_id, "account": str(payload.account_id), "amount": amount, "reference": payload.settlement_reference,
             "description": f"COD remittance for online order {str(order['id'])[:8]}", "date": payload.settlement_date,
             "payment": str(payment), "actor": _actor(db)})
        sync_receivable(db, company_id, receivable, invoice)
        db.execute(text("""insert into cod_settlement_items(settlement_id,company_id,order_id,invoice_id,amount)
            values(:settlement,:company,:order,:invoice,:amount)"""),
            {"settlement": str(settlement), "company": company_id, "order": str(order["id"]), "invoice": str(order["invoice_id"]), "amount": amount})
    db.commit()
    return cod_settlement(db, company_id, str(settlement))



def cod_settlement(db: Session, company_id: str, settlement_id: str) -> dict:
    row = db.execute(text("select * from cod_settlements where company_id=:company and id=:id"),
                     {"company": company_id, "id": settlement_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Settlement not found")
    items = db.execute(text("select order_id, invoice_id, amount from cod_settlement_items where settlement_id=:id order by order_id"),
                       {"id": settlement_id}).mappings().all()
    return {**dict(row), "items": [dict(item) for item in items]}


def cod_outstanding(db: Session, company_id: str) -> dict:
    settings = checkout_policy(db, company_id)
    rows = db.execute(text(f"""select o.id as order_id, o.status, o.dispatched_at, o.delivered_at, i.invoice_number, i.total,
            r.amount_received, i.total - r.amount_received as outstanding,
            (current_date - o.dispatched_at::date) as days_since_dispatch,
            (current_date - o.dispatched_at::date) > :overdue as overdue
        from shop_orders o join invoices i on i.id=o.invoice_id join receivables r on r.invoice_id=i.id
        where o.company_id=:company and o.payment_method='cod' and o.invoice_id is not null and r.status in ('UNPAID','PARTIAL')
        order by o.dispatched_at"""), {"company": company_id, "overdue": settings["cod_overdue_days"]}).mappings().all()
    settlements = db.execute(text("""select id, courier, settlement_reference, settlement_date, expected_amount, received_amount, shortfall_reason
        from cod_settlements where company_id=:company order by settlement_date desc, created_at desc limit 100"""),
        {"company": company_id}).mappings().all()
    return {"items": [dict(row) for row in rows], "settlements": [dict(row) for row in settlements],
            "total_outstanding": sum((Decimal(row["outstanding"]) for row in rows), Decimal("0"))}


def staff_orders(db: Session, company_id: str, offset: int = 0, status: str | None = None) -> dict:
    expire_orders(db, company_id)
    db.commit()
    query = f"select {ORDER_COLUMNS} from shop_orders where company_id=:company"
    params: dict = {"company": company_id, "offset": offset}
    if status:
        query += " and status=:status"
        params["status"] = status
    rows = db.execute(text(query + " order by created_at desc,id limit 50 offset :offset"), params).mappings().all()
    return {"items": [dict(row) for row in rows]}


# ---------------------------------------------------------------- enquiries

def create_enquiry(db: Session, company_id: str, payload: EnquiryInput) -> dict:
    product = db.execute(text("select name from products where id=:id and company_id=:company and is_active and catalog_visible"),
                         {"id": str(payload.product_id), "company": company_id}).scalar_one_or_none()
    if not product:
        raise HTTPException(422, "Choose an active product")
    store = get_store(db, company_id, str(payload.store_id)) if payload.store_id else None
    reference = "ENQ-" + secrets.token_hex(3).upper()
    row = db.execute(text("""insert into enquiries(company_id,reference,store_id,product_id,variant_id,quantity,shopper_name,shopper_phone,message)
        values(:company,:reference,:store,:product,:variant,:quantity,:name,:phone,:message) returning *"""),
        {"company": company_id, "reference": reference, "store": str(store["id"]) if store else None, "product": str(payload.product_id),
         "variant": str(payload.variant_id) if payload.variant_id else None, "quantity": payload.quantity,
         "name": payload.shopper_name, "phone": payload.shopper_phone, "message": payload.message}).mappings().one()
    db.commit()
    number = whatsapp_number(db, company_id, str(store["id"]) if store else None)
    message = f"Hi, enquiry {reference}: {payload.quantity} x {product}" + (f" at {store['name']}" if store else "") + \
              (f". {payload.message}" if payload.message else "")
    return {"reference": reference, "id": row["id"], "whatsapp_number": number,
            "whatsapp_link": f"https://wa.me/{number.lstrip('+')}?text={_url_encode(message)}" if number else None}


def _url_encode(value: str) -> str:
    from urllib.parse import quote
    return quote(value, safe="")


def whatsapp_number(db: Session, company_id: str, store_id: str | None) -> str | None:
    row = db.execute(text("""select coalesce((select whatsapp_number from stores where id=cast(:store as uuid) and company_id=:company),
        (select whatsapp_number from stores where company_id=:company and kind='online' and is_active order by created_at limit 1),
        (select whatsapp_number from companies where id=:company))"""), {"store": store_id, "company": company_id}).scalar_one()
    return row


def list_enquiries(db: Session, company_id: str, status: str | None = None) -> dict:
    query = """select e.*, p.name as product_name, v.variant_name, s.code as store_code
        from enquiries e join products p on p.id=e.product_id left join product_variants v on v.id=e.variant_id
        left join stores s on s.id=e.store_id where e.company_id=:company"""
    params: dict = {"company": company_id}
    if status:
        query += " and e.status=:status"
        params["status"] = status
    rows = db.execute(text(query + " order by e.created_at desc limit 200"), params).mappings().all()
    return {"items": [dict(row) for row in rows]}


def update_enquiry(db: Session, company_id: str, enquiry_id: str, payload: EnquiryUpdate) -> dict:
    if payload.status == "converted":
        if not payload.invoice_id:
            raise HTTPException(422, "Link the invoice that converted this enquiry")
        if not db.execute(text("select 1 from invoices where id=:id and company_id=:company"),
                          {"id": str(payload.invoice_id), "company": company_id}).first():
            raise HTTPException(404, "Invoice not found")
    row = db.execute(text("""update enquiries set status=:status, invoice_id=:invoice, handled_by=cast(:actor as uuid), updated_at=now()
        where id=:id and company_id=:company returning *"""),
        {"status": payload.status, "invoice": str(payload.invoice_id) if payload.invoice_id else None, "actor": _actor(db),
         "id": enquiry_id, "company": company_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Enquiry not found")
    db.commit()
    return dict(row)


# ---------------------------------------------------------------- nearby availability

def _distance_km(lat1, lng1, lat2, lng2) -> float:
    radius = 6371.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def nearby_availability(db: Session, company_id: str, product_id: str, variant_id: str | None,
                        lat: float | None, lng: float | None, pincode: str | None) -> dict:
    """Pickup-enabled shops with an availability band (never a count), sorted by distance when known."""
    from app.services.shop_stock import reserved_stock
    expire_orders(db, company_id)
    db.commit()
    moq = db.execute(text("select minimum_order_quantity from products where id=:id and company_id=:company and is_active and catalog_visible"),
                     {"id": product_id, "company": company_id}).scalar_one_or_none()
    if moq is None:
        raise HTTPException(404, "Product not found")
    stores = db.execute(text("""select s.id, s.code, s.name, s.address, s.pincode, s.latitude, s.longitude, s.whatsapp_number,
            coalesce((select sum(quantity) from stock_balances b where b.company_id=s.company_id and b.store_id=s.id
                and b.product_id=cast(:product as uuid) and b.variant_id is not distinct from cast(:variant as uuid)),0) as balance
        from stores s where s.company_id=:company and s.is_active and s.holds_stock and s.allows_pickup"""),
        {"company": company_id, "product": product_id, "variant": variant_id}).mappings().all()
    default_number = whatsapp_number(db, company_id, None)
    items = []
    for store in stores:
        available = Decimal(str(store["balance"])) - reserved_stock(db, company_id, product_id, variant_id, str(store["id"]))
        band = "unavailable" if available <= 0 else "few_left" if available < max(Decimal(3), Decimal(moq)) else "available"
        distance = None
        if lat is not None and lng is not None and store["latitude"] is not None and store["longitude"] is not None:
            distance = round(_distance_km(lat, lng, store["latitude"], store["longitude"]), 1)
        rank = (0, distance) if distance is not None else (1, 0 if pincode and store["pincode"] == pincode else
                                                           2 if pincode and store["pincode"] and store["pincode"][:3] == pincode[:3] else 3)
        items.append({"store_id": store["id"], "code": store["code"], "name": store["name"], "address": store["address"],
                      "pincode": store["pincode"], "distance_km": distance, "availability": band,
                      "whatsapp_number": store["whatsapp_number"] or default_number, "_rank": rank})
    items.sort(key=lambda item: (item["_rank"], item["name"]))
    for item in items:
        item.pop("_rank")
    return {"items": items, "default_whatsapp_number": default_number}
