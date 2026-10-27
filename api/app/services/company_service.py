import json

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.company import CompanyUpdate, SiteTheme


class CompanyService:
    def __init__(self, db: Session):
        self.db = db

    def get(self, company_id: str | None = None) -> dict:
        row = self.db.execute(
            text("""
                select * from companies
                where is_active = true
                  and (cast(:company_id as uuid) is null or id = cast(:company_id as uuid))
                order by created_at asc, id asc limit 1
            """),
            {"company_id": company_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Company not found")
        return dict(row)

    def update(self, payload: CompanyUpdate, company_id: str | None = None) -> dict:
        company = self.get(company_id)
        values = payload.model_dump()
        values["id"] = str(company["id"])
        values["social_links"] = json.dumps(values["social_links"])
        values["invoice_settings"] = json.dumps(values["invoice_settings"])
        values["site_theme"] = json.dumps(values["site_theme"]) if values["site_theme"] is not None else None
        row = self.db.execute(
            text("""
                update companies set company_name = :company_name, nickname = :nickname,
                    address = :address, gst_number = :gst_number, udyam_number = :udyam_number,
                    phone = :phone, email = :email, website = :website, logo_url = :logo_url,
                    social_links = cast(:social_links as jsonb),
                    invoice_settings = cast(:invoice_settings as jsonb),
                    site_theme = coalesce(cast(:site_theme as jsonb), site_theme), updated_at = now()
                where id = :id returning *
            """), values,
        ).mappings().one()
        self.db.commit()
        return dict(row)

    def update_site_theme(self, theme: SiteTheme, company_id: str | None = None) -> dict:
        company = self.get(company_id)
        row = self.db.execute(text("""
            update companies set site_theme = cast(:theme as jsonb), updated_at = now()
            where id = :id returning *
        """), {"id": str(company["id"]), "theme": theme.model_dump_json()}).mappings().one()
        self.db.commit()
        return dict(row)