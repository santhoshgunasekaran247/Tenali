from collections import defaultdict
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.schemas.inventory import StockAdjustment
from app.services.inventory_service import InventoryService


def active_hsn(db, company_id: str, code: str | None) -> bool:
    return bool(code) and db.execute(text("select 1 from hsn_masters where company_id=:company and code=:code and is_active=true"),
                                     {"company": company_id, "code": code}).scalar_one_or_none() is not None


def create_draft_products(db, company_id: str, lines, vendor_id: str, selling_prices: dict[str, Decimal] | None = None) -> None:
    """Purchase lines marked as new items become draft inventory products mapped to the bill's vendor."""
    from app.services.financial_amounts import line_amounts
    created: dict[str, str] = {}
    for line in lines:
        if not getattr(line, "new_product", False):
            continue
        if line.product_id or line.variant_id:
            raise HTTPException(422, "A new inventory item cannot also select an existing product")
        name = " ".join(line.description.split())
        if not name:
            raise HTTPException(422, "Enter a name for the new inventory item")
        if not active_hsn(db, company_id, line.hsn):
            raise HTTPException(422, f"Choose an active HSN/SAC code for {name}")
        key = name.casefold()
        if key not in created:
            existing = db.execute(text("select name from products where company_id=:company and lower(name)=lower(:name) and is_active=true limit 1"),
                                  {"company": company_id, "name": name}).scalar_one_or_none()
            if existing:
                raise HTTPException(409, f"{existing} already exists in Product Inventory. Select it from the product list instead of adding a new item.")
            buying_price, _ = line_amounts(Decimal("1"), line.rate, line.gst_rate, bool(line.price_includes_gst))
            prices = selling_prices or {}
            product_id = str(db.execute(text("""insert into products(company_id,portal_product_id,name,hsn_code,selling_price,
                is_draft,catalog_visible,preferred_vendor_id)
                values(:company,:code,:name,:hsn,:selling_price,true,false,:vendor) returning id"""),
                {"company": company_id, "code": f"PRD-{uuid4().hex[:12].upper()}", "name": name, "hsn": line.hsn,
                 "selling_price": prices.get(key), "vendor": vendor_id}).scalar_one())
            db.execute(text("insert into vendor_contributions(vendor_id,product_id,buying_price,is_active) values(:vendor,:product,:price,true)"),
                       {"vendor": vendor_id, "product": product_id, "price": buying_price})
            created[key] = product_id
        line.product_id = UUID(created[key])
        line.new_product = False


def resolve_product_lines(db, company_id: str, lines, vendor_id: str | None = None, allow_drafts: bool = False,
                          *, persist_hsn: bool = True):
    for line in lines:
        if line.variant_id and not line.product_id:
            raise HTTPException(422, "A variant requires its parent product")
        if not line.product_id:
            continue
        product = db.execute(text("select * from products where id=:id and company_id=:company and is_active=true"),
                             {"id": str(line.product_id), "company": company_id}).mappings().first()
        if not product:
            raise HTTPException(422, "Select an active product from this company")
        if product.get("is_draft") and not allow_drafts:
            raise HTTPException(422, f"{product['name']} is a draft product. Confirm it in Product Inventory before selling it")
        variant = None
        if line.variant_id:
            variant = db.execute(text("select * from product_variants where id=:id and product_id=:product and is_active=true"),
                                 {"id": str(line.variant_id), "product": str(line.product_id)}).mappings().first()
            if not variant:
                raise HTTPException(422, "Select an active variant belonging to the product")
        elif db.execute(text("select id from product_variants where product_id=:product and is_active=true limit 1"), {"product": str(line.product_id)}).scalar_one_or_none():
            raise HTTPException(422, f"Select a variant for {product['name']}")
        hsn = product["hsn_code"]
        if not hsn:
            # Products without an HSN take the code chosen on the line, and keep it for future bills.
            if not active_hsn(db, company_id, line.hsn):
                raise HTTPException(422, f"Choose an HSN/SAC code for {product['name']}")
            if persist_hsn:
                db.execute(text("""update products set hsn_code=:hsn, updated_at=now()
                    where id=:id and company_id=:company and coalesce(hsn_code,'')=''"""),
                    {"hsn": line.hsn, "id": str(line.product_id), "company": company_id})
                hsn = db.execute(text("select hsn_code from products where id=:id"), {"id": str(line.product_id)}).scalar_one()
            else:
                hsn = line.hsn
        if vendor_id and not db.execute(text("""select id from vendor_contributions where product_id=:product
            and variant_id is not distinct from cast(:variant as uuid) and vendor_id=:vendor and is_active=true limit 1"""),
            {"product": str(line.product_id), "variant": str(line.variant_id) if line.variant_id else None, "vendor": vendor_id}).scalar_one_or_none():
            raise HTTPException(422, "The selected vendor is not mapped to this product/variant")
        line.hsn = hsn
        line.description = product["name"] + (f" - {variant['variant_name']}" if variant else "")


def purchase_line_totals(payload):
    from app.services.financial_amounts import line_amounts
    subtotal, gst_total = Decimal("0"), Decimal("0")
    items = []
    for line in payload.lines:
        inclusive = bool(line.price_includes_gst)
        taxable, gst = line_amounts(line.quantity, line.rate, line.gst_rate, inclusive)
        items.append({**line.model_dump(mode="json", exclude={"new_product"}),
                      "price_includes_gst": inclusive, "taxable": str(taxable),
                      "gst_amount": str(gst), "total": str(taxable + gst)})
        subtotal += taxable
        gst_total += gst
    payload.subtotal, payload.gst_total, payload.total = subtotal, gst_total, subtotal + gst_total
    return items


def book_stock(db, company_id: str, lines: list[dict], direction: str, source: str, source_id: str, store_id: str):
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
                             commit=False, reference_type=source, reference_id=source_id, store_id=store_id)


def booked_store(db, company_id: str, source: str, source_id: str) -> str | None:
    """Store that originally booked stock for a document, so cancellations return it to the same place."""
    row = db.execute(text("""select store_id from stock_movements where company_id=:company and reference_type=:source
        and reference_id=:id order by created_at limit 1"""), {"company": company_id, "source": source, "id": source_id}).scalar_one_or_none()
    return str(row) if row else None