from __future__ import annotations

from collections.abc import Mapping

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


def _to_dict(row: Mapping[str, object] | object) -> dict:
    if isinstance(row, Mapping):
        return dict(row)
    return dict(row._mapping)


def _catalog_base_query() -> str:
    return """
        select
            p.id,
            p.portal_product_id,
            p.name,
            p.description,
            p.image_url,
            p.image_urls,
            p.mrp_display,
            p.selling_price_display,
            p.best_seller,
            p.sru_special,
            p.home_order,
            p.is_active,
            b.code as brand_code,
            b.name as brand_name,
            c.code as category_slug,
            coalesce(c.display_title, c.name) as category_title,
            coalesce(c.description, '') as category_description,
            coalesce(sb.quantity, 0) as stock_qty
        from products p
        left join brands b on b.id = p.brand_id
        left join product_categories c on c.id = p.category_id
        left join stock_balances sb on sb.product_id = p.id and sb.variant_id is null
        where p.company_id = :company_id and p.is_active = true
    """


class CatalogService:
    def __init__(self, db: Session):
        self.db = db

    def _resolve_company_id(self, company_id: str | None) -> str:
        if company_id:
            return company_id

        first_company = self.db.execute(
            text("select id from companies where is_active = true order by created_at asc limit 1")
        ).scalar_one_or_none()
        if not first_company:
            raise HTTPException(status_code=404, detail="No company configured")
        return str(first_company)

    def home(self, company_id: str | None = None) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)

        company_row = self.db.execute(
            text(
                """
                select id, company_name, nickname, logo_url, phone, email
                from companies
                where id = :company_id and is_active = true
                """
            ),
            {"company_id": resolved_company_id},
        ).mappings().first()
        if not company_row:
            raise HTTPException(status_code=404, detail="Company not found")

        categories = self.db.execute(
            text(
                """
                select
                    code as category_slug,
                    name,
                    coalesce(display_title, name) as category_title,
                    coalesce(description, '') as category_description,
                    image_url,
                    home_order
                from product_categories
                where company_id = :company_id and is_active = true
                order by home_order asc, name asc
                """
            ),
            {"company_id": resolved_company_id},
        ).mappings().all()

        products = self.db.execute(
            text(_catalog_base_query() + " order by p.home_order asc, p.name asc"),
            {"company_id": resolved_company_id},
        ).mappings().all()

        brands = self.db.execute(
            text(
                """
                select code, name, coalesce(description, '') as description
                from brands
                where company_id = :company_id and is_active = true
                order by name asc
                """
            ),
            {"company_id": resolved_company_id},
        ).mappings().all()

        all_products = [_to_dict(row) for row in products]
        best_sellers = [row for row in all_products if row.get("best_seller")]
        sru_specials = [row for row in all_products if row.get("sru_special")]

        return {
            "company": _to_dict(company_row),
            "brands": [_to_dict(row) for row in brands],
            "categories": [_to_dict(row) for row in categories],
            "best_sellers": best_sellers[:8],
            "sru_specials": sru_specials[:8],
        }

    def list(self, company_id: str | None = None, brand: str | None = None, category: str | None = None) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)

        company_row = self.db.execute(
            text(
                """
                select id, company_name, nickname, logo_url, phone, email
                from companies
                where id = :company_id and is_active = true
                """
            ),
            {"company_id": resolved_company_id},
        ).mappings().first()
        if not company_row:
            raise HTTPException(status_code=404, detail="Company not found")

        brands = self.db.execute(
            text(
                """
                select code, name, coalesce(description, '') as description
                from brands
                where company_id = :company_id and is_active = true
                order by name asc
                """
            ),
            {"company_id": resolved_company_id},
        ).mappings().all()

        categories = self.db.execute(
            text(
                """
                select
                    code as category_slug,
                    name,
                    coalesce(display_title, name) as category_title,
                    coalesce(description, '') as category_description,
                    image_url,
                    home_order
                from product_categories
                where company_id = :company_id and is_active = true
                order by home_order asc, name asc
                """
            ),
            {"company_id": resolved_company_id},
        ).mappings().all()

        query = _catalog_base_query()
        params: dict[str, object] = {"company_id": resolved_company_id}

        if brand:
            query += " and b.code = :brand_code"
            params["brand_code"] = brand

        if category and category != "all":
            query += " and c.code = :category_slug"
            params["category_slug"] = category

        query += " order by p.home_order asc, p.name asc"

        products = self.db.execute(text(query), params).mappings().all()

        selected_brand = None
        if brand:
            selected_brand = next((row for row in brands if row["code"] == brand), None)

        selected_category = None
        if category and category != "all":
            selected_category = next(
                (row for row in categories if row["category_slug"] == category),
                None,
            )

        return {
            "company": _to_dict(company_row),
            "brands": [_to_dict(row) for row in brands],
            "categories": [_to_dict(row) for row in categories],
            "products": [_to_dict(row) for row in products],
            "selected_brand": _to_dict(selected_brand) if selected_brand else None,
            "selected_category": _to_dict(selected_category) if selected_category else None,
        }

    def product_detail(self, product_id: str, company_id: str | None = None) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)

        row = self.db.execute(
            text(_catalog_base_query() + " and p.id = :product_id limit 1"),
            {"company_id": resolved_company_id, "product_id": product_id},
        ).mappings().first()

        if not row:
            raise HTTPException(status_code=404, detail="Product not found")

        product = _to_dict(row)
        image_urls = (product.get("image_urls") or "").split("|")
        product["gallery"] = [url.strip() for url in image_urls if url.strip()]
        if not product["gallery"] and product.get("image_url"):
            product["gallery"] = [product["image_url"]]

        return {"product": product}
