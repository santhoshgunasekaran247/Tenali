from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException


def resolve_catalog_price(mrp, price, discount, mode: str) -> dict:
    mrp_value = Decimal(str(mrp)) if mrp is not None else None
    discount_value = Decimal(str(discount or 0))
    price_value = Decimal(str(price)) if price is not None else None
    if mode not in {"price", "discount"}:
        raise HTTPException(status_code=422, detail="Invalid pricing mode")
    values = [value for value in [mrp_value, price_value, discount_value] if value is not None]
    if any(not value.is_finite() or value < 0 for value in values) or discount_value > 100:
        raise HTTPException(status_code=422, detail="Prices must be non-negative and discount must be between 0 and 100")
    if mode == "discount":
        price_value = (mrp_value * (1 - discount_value / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if mrp_value is not None else None
    elif mrp_value is not None and price_value is not None:
        if price_value > mrp_value:
            raise HTTPException(status_code=422, detail="Catalog price cannot exceed the preferred vendor MRP")
        discount_value = ((mrp_value - price_value) * 100 / mrp_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if mrp_value else None
    else:
        discount_value = None
    return {"effective_mrp": mrp_value, "catalog_price": price_value, "effective_discount": discount_value}