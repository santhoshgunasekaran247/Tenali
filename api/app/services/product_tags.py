from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.storefront import ProductTagsUpdate
from app.services.company_service import CompanyService


class ProductTagsService:
    def __init__(self, db: Session):
        self.db = db

    def list(self, company_id: str | None = None) -> list[dict]:
        company = CompanyService(self.db).get(company_id)
        company_key = str(company["id"])
        tags = self.db.execute(text("""
            select id, code, name
            from product_tags
            where company_id = :company_id
            order by name, code
        """), {"company_id": company_key}).mappings().all()
        result = []
        for tag in tags:
            row = dict(tag)
            row["id"] = str(row["id"])
            row["product_ids"] = [
                str(product_id) for product_id in self.db.execute(text("""
                    select product_id
                    from product_tag_products
                    where company_id = :company_id and tag_id = :tag_id
                    order by product_id
                """), {"company_id": company_key, "tag_id": row["id"]}).scalars().all()
            ]
            result.append(row)
        return result

    def replace(self, payload: ProductTagsUpdate, company_id: str | None = None) -> list[dict]:
        company = CompanyService(self.db).get(company_id)
        company_key = str(company["id"])
        product_ids = list({str(product_id) for tag in payload.tags for product_id in tag.product_ids})
        if product_ids:
            found = self.db.execute(text("""
                select count(*)
                from products
                where company_id = :company_id and id = any(cast(:ids as uuid[]))
                  and is_active = true and catalog_visible = true
            """), {"company_id": company_key, "ids": product_ids}).scalar_one()
            if found != len(product_ids):
                raise HTTPException(status_code=422, detail="Tags can only be assigned to active, visible products in this workspace")

        self.db.execute(text("delete from product_tags where company_id = :company_id"), {"company_id": company_key})
        for tag in payload.tags:
            tag_id = self.db.execute(text("""
                insert into product_tags(company_id, code, name)
                values (:company_id, :code, :name)
                returning id
            """), {"company_id": company_key, "code": tag.code, "name": tag.name}).scalar_one()
            for product_id in tag.product_ids:
                self.db.execute(text("""
                    insert into product_tag_products(company_id, tag_id, product_id)
                    values (:company_id, :tag_id, :product_id)
                """), {"company_id": company_key, "tag_id": str(tag_id), "product_id": str(product_id)})
        self.db.commit()
        return self.list(company_key)
