from decimal import Decimal

from sqlalchemy import text

# Orders that hold stock: unpaid prepaid checkouts inside their payment window, captured prepaid
# orders awaiting dispatch, approved COD orders, and pickup orders awaiting collection.
HOLDING_STATUSES = ("awaiting_payment", "paid", "confirmed", "ready_for_pickup", "shipping_pending", "shipment_booked")


def reserved_stock(db, company_id: str, product_id: str, variant_id: str | None, store_id: str,
                   exclude_order: str | None = None):
    return Decimal(str(db.execute(text("""select coalesce(sum((item->>'quantity')::numeric),0)
        from shop_orders orders cross join lateral jsonb_array_elements(orders.items) item
        where orders.company_id=:company and orders.status=any(:statuses)
        and (orders.expires_at is null or orders.expires_at>now())
        and coalesce(orders.ship_from_store_id,
                     case when orders.payment_method='pay_at_pickup' then orders.pickup_store_id end,
                     (select fulfilment_store_id from stores where id=orders.store_id))=cast(:store as uuid)
        and (cast(:exclude as text) is null or orders.id::text<>cast(:exclude as text))
        and item->>'product_id'=:product
        and item->>'variant_id' is not distinct from cast(:variant as text)"""),
        {"company": company_id, "product": product_id, "variant": variant_id, "store": store_id,
         "exclude": exclude_order, "statuses": list(HOLDING_STATUSES)}).scalar_one()))
