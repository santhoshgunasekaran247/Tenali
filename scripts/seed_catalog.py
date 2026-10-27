import csv
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "tenali-v31-exact-prototype" / "data"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _to_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"yes", "true", "1", "y"}


def _to_float(value: str):
    raw = (value or "").strip()
    if not raw or "-" in raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _coalesce(*values: str) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def _load_company(conn, company_rows: list[dict[str, str]]) -> str:
    row = company_rows[0]
    company_name = row["company_name"].strip()

    existing = conn.execute(
        text("select id from companies where company_name = :company_name limit 1"),
        {"company_name": company_name},
    ).scalar_one_or_none()

    if existing:
        conn.execute(
            text(
                """
                update companies
                set
                    nickname = :nickname,
                    logo_url = :logo_url,
                    gst_number = :gst_number,
                    udyam_number = :udyam_number,
                    phone = :phone,
                    email = :email,
                    address = :address,
                    website = :website,
                    social_links = cast(:social_links as jsonb),
                    updated_at = now()
                where id = :id
                """
            ),
            {
                "id": existing,
                "nickname": _coalesce(row.get("nickname", ""), "SRU"),
                "logo_url": row.get("logo", ""),
                "gst_number": row.get("gst_number", ""),
                "udyam_number": row.get("udhyam_number", ""),
                "phone": row.get("phone", ""),
                "email": row.get("email", ""),
                "address": row.get("address", ""),
                "website": row.get("website", ""),
                "social_links": "{}",
            },
        )
        return existing

    new_id = conn.execute(
        text(
            """
            insert into companies (
                company_name,
                nickname,
                logo_url,
                gst_number,
                udyam_number,
                phone,
                email,
                address,
                website,
                social_links,
                is_active
            )
            values (
                :company_name,
                :nickname,
                :logo_url,
                :gst_number,
                :udyam_number,
                :phone,
                :email,
                :address,
                :website,
                cast(:social_links as jsonb),
                true
            )
            returning id
            """
        ),
        {
            "company_name": company_name,
            "nickname": _coalesce(row.get("nickname", ""), "SRU"),
            "logo_url": row.get("logo", ""),
            "gst_number": row.get("gst_number", ""),
            "udyam_number": row.get("udhyam_number", ""),
            "phone": row.get("phone", ""),
            "email": row.get("email", ""),
            "address": row.get("address", ""),
            "website": row.get("website", ""),
            "social_links": "{}",
        },
    ).scalar_one()
    return new_id


def _upsert_brands(conn, company_id: str):
    rows = _read_csv(DATA_DIR / "brands.csv")
    for row in rows:
        conn.execute(
            text(
                """
                insert into brands (company_id, code, name, description, is_active)
                values (:company_id, :code, :name, :description, true)
                on conflict (company_id, name)
                do update set
                    code = excluded.code,
                    description = excluded.description,
                    is_active = true
                """
            ),
            {
                "company_id": company_id,
                "code": row["id"].strip(),
                "name": row["name"].strip(),
                "description": row.get("description", "").strip(),
            },
        )


def _upsert_categories(conn, company_id: str):
    product_rows = _read_csv(DATA_DIR / "products.csv")
    category_rows = [row for row in product_rows if row.get("row_type", "").strip() == "category"]

    for row in category_rows:
        name = _coalesce(row.get("category_title", ""), row.get("name", ""), row.get("category_slug", ""))
        conn.execute(
            text(
                """
                insert into product_categories (
                    company_id,
                    code,
                    name,
                    display_title,
                    description,
                    image_url,
                    home_order,
                    is_active
                )
                values (
                    :company_id,
                    :code,
                    :name,
                    :display_title,
                    :description,
                    :image_url,
                    :home_order,
                    true
                )
                on conflict (company_id, name)
                do update set
                    code = excluded.code,
                    display_title = excluded.display_title,
                    description = excluded.description,
                    image_url = excluded.image_url,
                    home_order = excluded.home_order,
                    is_active = true
                """
            ),
            {
                "company_id": company_id,
                "code": row.get("category_slug", "").strip() or None,
                "name": name,
                "display_title": row.get("category_title", "").strip() or name,
                "description": row.get("category_description", "").strip() or row.get("description", "").strip(),
                "image_url": row.get("image", "").strip(),
                "home_order": int(row.get("home_order") or 999),
            },
        )


def _upsert_products(conn, company_id: str):
    product_rows = _read_csv(DATA_DIR / "products.csv")
    product_rows = [row for row in product_rows if row.get("row_type", "").strip() == "product"]

    brand_id_by_code = {
        row["code"]: row["id"]
        for row in conn.execute(
            text("select id, code from brands where company_id = :company_id and code is not null"),
            {"company_id": company_id},
        ).mappings().all()
    }

    category_id_by_code = {
        row["code"]: row["id"]
        for row in conn.execute(
            text("select id, code from product_categories where company_id = :company_id and code is not null"),
            {"company_id": company_id},
        ).mappings().all()
    }

    for row in product_rows:
        brand_id = brand_id_by_code.get(row.get("brand", "").strip())
        category_id = category_id_by_code.get(row.get("category_slug", "").strip())

        conn.execute(
            text(
                """
                insert into products (
                    company_id,
                    portal_product_id,
                    sku,
                    name,
                    brand_id,
                    category_id,
                    description,
                    image_url,
                    image_urls,
                    mrp,
                    mrp_display,
                    selling_price,
                    selling_price_display,
                    hsn_code,
                    gst_rate,
                    uom,
                    best_seller,
                    sru_special,
                    home_order,
                    reorder_level,
                    is_active
                )
                values (
                    :company_id,
                    :portal_product_id,
                    :sku,
                    :name,
                    :brand_id,
                    :category_id,
                    :description,
                    :image_url,
                    :image_urls,
                    :mrp,
                    :mrp_display,
                    :selling_price,
                    :selling_price_display,
                    :hsn_code,
                    :gst_rate,
                    :uom,
                    :best_seller,
                    :sru_special,
                    :home_order,
                    :reorder_level,
                    true
                )
                on conflict (company_id, portal_product_id)
                do update set
                    sku = excluded.sku,
                    name = excluded.name,
                    brand_id = excluded.brand_id,
                    category_id = excluded.category_id,
                    description = excluded.description,
                    image_url = excluded.image_url,
                    image_urls = excluded.image_urls,
                    mrp = excluded.mrp,
                    mrp_display = excluded.mrp_display,
                    selling_price = excluded.selling_price,
                    selling_price_display = excluded.selling_price_display,
                    hsn_code = excluded.hsn_code,
                    gst_rate = excluded.gst_rate,
                    uom = excluded.uom,
                    best_seller = excluded.best_seller,
                    sru_special = excluded.sru_special,
                    home_order = excluded.home_order,
                    reorder_level = excluded.reorder_level,
                    is_active = true,
                    updated_at = now()
                """
            ),
            {
                "company_id": company_id,
                "portal_product_id": row["portal_product_id"].strip(),
                "sku": row.get("portal_product_id", "").strip() or None,
                "name": row["name"].strip(),
                "brand_id": brand_id,
                "category_id": category_id,
                "description": row.get("description", "").strip(),
                "image_url": row.get("image", "").strip(),
                "image_urls": row.get("images", "").strip(),
                "mrp": _to_float(row.get("mrp", "")),
                "mrp_display": row.get("mrp", "").strip() or None,
                "selling_price": _to_float(row.get("our_price", "")),
                "selling_price_display": row.get("our_price", "").strip() or None,
                "hsn_code": row.get("hsn", "").strip() or None,
                "gst_rate": _to_float(row.get("gst_rate", "")),
                "uom": row.get("uom", "").strip() or None,
                "best_seller": _to_bool(row.get("best_seller", "")),
                "sru_special": _to_bool(row.get("sru_special", "")),
                "home_order": int(row.get("home_order") or 999),
                "reorder_level": 0,
            },
        )


def _upsert_stock(conn, company_id: str):
    rows = _read_csv(DATA_DIR / "stock.csv")

    portal_to_product = {
        row["portal_product_id"]: row["id"]
        for row in conn.execute(
            text("select id, portal_product_id from products where company_id = :company_id"),
            {"company_id": company_id},
        ).mappings().all()
    }

    for row in rows:
        portal_id = row.get("portal_product_id", "").strip()
        product_id = portal_to_product.get(portal_id)
        if not product_id:
            continue

        qty = float(row.get("qty_on_hand", "0") or 0)
        reorder_level = float(row.get("reorder_level", "0") or 0)

        conn.execute(
            text(
                """
                update products
                set reorder_level = :reorder_level, updated_at = now()
                where id = :product_id
                """
            ),
            {"product_id": product_id, "reorder_level": reorder_level},
        )

        conn.execute(
            text(
                """
                insert into stock_balances (
                    company_id,
                    product_id,
                    variant_id,
                    quantity
                )
                values (
                    :company_id,
                    :product_id,
                    null,
                    :quantity
                )
                on conflict (company_id, product_id, variant_id)
                do update set quantity = excluded.quantity
                """
            ),
            {"company_id": company_id, "product_id": product_id, "quantity": qty},
        )


def main() -> None:
    load_dotenv(REPO_ROOT / "api" / ".env", override=True)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    engine = create_engine(database_url, pool_pre_ping=True)

    company_rows = _read_csv(DATA_DIR / "company.csv")

    with engine.begin() as conn:
        company_id = _load_company(conn, company_rows)
        _upsert_brands(conn, company_id)
        _upsert_categories(conn, company_id)
        _upsert_products(conn, company_id)
        _upsert_stock(conn, company_id)

    print("Catalog seed completed.")


if __name__ == "__main__":
    main()
