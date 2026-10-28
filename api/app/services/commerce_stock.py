from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import text

from app.schemas.inventory import StockAdjustment
from app.services.inventory_service import InventoryService


def resolve_product_lines(db, company_id: str, lines, vendor_id: str | None = None):
    for line in lines:
        if line.variant_id and not line.product_id:
            raise HTTPException(422, "A variant requires its parent product")
        if not line.product_id:
            continue
        product = db.execute(text("select * from products where id=:id and company_id=:company and is_active=true"),
                             {"id": str(line.product_id), "company": company_id}).mappings().first()
        if not product:
            raise HTTPException(422, "Select an active product from this company")
        variant = None
        if line.variant_id:
            variant = db.execute(text("select * from product_variants where id=:id and product_id=:product and is_active=true"),
                                 {"id": str(line.variant_id), "product": str(line.product_id)}).mappings().first()
            if not variant:
                raise HTTPException(422, "Select an active variant belonging to the product")
        elif db.execute(text("select id from product_variants where product_id=:product and is_active=true limit 1"), {"product": str(line.product_id)}).scalar_one_or_none():
            raise HTTPException(422, f"Select a variant for {product['name']}")
        if not product["hsn_code"]:
            raise HTTPException(422, f"Set an HSN/SAC code on {product['name']} before posting")
        if vendor_id and not db.execute(text("""select id from vendor_contributions where product_id=:product
            and variant_id is not distinct from cast(:variant as uuid) and vendor_id=:vendor and is_active=true limit 1"""),
            {"product": str(line.product_id), "variant": str(line.variant_id) if line.variant_id else None, "vendor": vendor_id}).scalar_one_or_none():
            raise HTTPException(422, "The selected vendor is not mapped to this product/variant")
        line.hsn = product["hsn_code"]
        line.description = product["name"] + (f" - {variant['variant_name']}" if variant else "")


def book_stock(db, company_id: str, lines: list[dict], direction: str, source: str, source_id: str):
    grouped = defaultdict(Decimal)
    for line in lines:
        if line.get("product_id"):
            grouped[(str(line["product_id"]), str(line["variant_id"]) if line.get("variant_id") else None)] += Decimal(str(line["quantity"]))
    service = InventoryService(db, company_id)
    for (product_id, variant_id), quantity in sorted(grouped.items(), key=lambda entry: (entry[0][0], entry[0][1] or "")):
        if db.execute(text("""select id from stock_movements where company_id=:company and product_id=:product
            and variant_id is not distinct from cast(:variant as uuid) and reference_type=:source and reference_id=:id limit 1"""),
            {"company": company_id, "product": product_id, "variant": variant_id, "source": source, "id": source_id}).scalar_one_or_none():
            continue
        service.adjust_stock(product_id, StockAdjustment(variant_id=variant_id, direction=direction, quantity=quantity, notes=f"{source}: {source_id}"),
                             commit=False, reference_type=source, reference_id=source_id)