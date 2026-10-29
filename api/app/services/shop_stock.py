from decimal import Decimal

from sqlalchemy import text


def reserved_stock(db, company_id: str, product_id: str, variant_id: str | None, exclude_order: str | None = None):
    return Decimal(str(db.execute(text("""select coalesce(sum((item->>'quantity')::numeric),0)
        from shop_orders orders cross join lateral jsonb_array_elements(orders.items) item
        where orders.company_id=:company and orders.status='awaiting_payment'
        and orders.created_at>now()-interval '30 minutes'
        and (cast(:exclude as text) is null or orders.id::text<>cast(:exclude as text))
        and item->>'product_id'=:product
        and item->>'variant_id' is not distinct from cast(:variant as text)"""),
        {"company": company_id, "product": product_id, "variant": variant_id, "exclude": exclude_order}).scalar_one()))
