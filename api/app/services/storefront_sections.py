import json

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.storefront import StorefrontSectionsUpdate
from app.services.company_service import CompanyService
from app.services.object_storage import FileStore


class StorefrontSectionsService:
    def __init__(self, db: Session):
        self.db = db

    def list(self, company_id: str | None = None) -> list[dict]:
        company = CompanyService(self.db).get(company_id)
        sections = self.db.execute(text("""
            select id, section_key, section_type, title, eyebrow, description, image_url,
                   sort_order, is_enabled, configuration
            from storefront_sections
            where company_id = :company_id
            order by sort_order, id
        """), {"company_id": str(company["id"])}).mappings().all()
        result = []
        for section in sections:
            row = dict(section)
            row.update(product_ids=[], category_ids=[], brand_ids=[])
            if row["section_type"] != "hero":
                table, entity_key, response_key = {
                    "products": ("storefront_section_products", "product_id", "product_ids"),
                    "categories": ("storefront_section_categories", "category_id", "category_ids"),
                    "brands": ("storefront_section_brands", "brand_id", "brand_ids"),
                }[row["section_type"]]
                row[response_key] = [
                    str(item[entity_key]) for item in self.db.execute(
                        text(f"""
                            select {entity_key} from {table}
                            where company_id = :company_id and section_id = :section_id
                            order by sort_order, {entity_key}
                        """),
                        {"company_id": str(company["id"]), "section_id": str(row["id"])},
                    ).mappings().all()
                ]
            row["id"] = str(row["id"])
            result.append(row)
        return result

    def replace(self, payload: StorefrontSectionsUpdate, company_id: str | None = None) -> list[dict]:
        company = CompanyService(self.db).get(company_id)
        company_key = str(company["id"])
        files = FileStore(self.db)
        for section in payload.sections:
            if section.section_type == "hero":
                continue
            item_table, item_column, ids = {
                "products": ("products", "id", section.product_ids),
                "categories": ("product_categories", "id", section.category_ids),
                "brands": ("brands", "id", section.brand_ids),
            }[section.section_type]
            if ids:
                active_clause = " and is_active = true"
                if section.section_type == "products":
                    active_clause += " and catalog_visible = true"
                found = self.db.execute(text(
                    f"select count(*) from {item_table} where company_id = :company_id "
                    f"and {item_column} = any(cast(:ids as uuid[])){active_clause}"
                ), {"company_id": company_key, "ids": [str(item) for item in ids]}).scalar_one()
                if found != len(ids):
                    raise HTTPException(status_code=422, detail=f"{section.section_type.title()} must belong to this workspace and be active")

        self.db.execute(text("delete from storefront_sections where company_id = :company_id"), {"company_id": company_key})
        for section in payload.sections:
            image_url = files.image(company_key, section.image_url) if section.image_url else None
            section_id = self.db.execute(text("""
                insert into storefront_sections(
                    company_id, section_key, section_type, title, eyebrow, description,
                    image_url, sort_order, is_enabled, configuration
                )
                values (
                    :company_id, :section_key, :section_type, :title, :eyebrow, :description,
                    :image_url, :sort_order, :is_enabled, cast(:configuration as jsonb)
                )
                returning id
            """), {
                "company_id": company_key,
                "section_key": section.section_key,
                "section_type": section.section_type,
                "title": section.title,
                "eyebrow": section.eyebrow,
                "description": section.description,
                "image_url": image_url,
                "sort_order": section.sort_order,
                "is_enabled": section.is_enabled,
                "configuration": json.dumps(section.configuration),
            }).scalar_one()
            if section.section_type == "hero":
                continue
            table, entity_column, ids = {
                "products": ("storefront_section_products", "product_id", section.product_ids),
                "categories": ("storefront_section_categories", "category_id", section.category_ids),
                "brands": ("storefront_section_brands", "brand_id", section.brand_ids),
            }[section.section_type]
            for position, entity_id in enumerate(ids):
                self.db.execute(text(f"""
                    insert into {table}(company_id, section_id, {entity_column}, sort_order)
                    values(:company_id, :section_id, :entity_id, :sort_order)
                """), {
                    "company_id": company_key,
                    "section_id": str(section_id),
                    "entity_id": str(entity_id),
                    "sort_order": position,
                })
        self.db.commit()
        return self.list(company_key)
