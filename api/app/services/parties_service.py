from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.parties import PartyCreate, PartyUpdate

ALLOWED_PARTY_TYPES = {
    "customer",
    "vendor",
    "customer_vendor",
    "friend",
    "employee",
    "other",
}


class PartiesService:
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

    def list(self, company_id: str | None, search: str | None = None, active_only: bool = True) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)
        query = """
            select
                id,
                company_id,
                party_type,
                nickname,
                legal_name,
                contact_person,
                phone,
                email,
                address,
                gst_number,
                is_active
            from parties
            where company_id = :company_id
        """
        params: dict[str, object] = {"company_id": resolved_company_id}

        if active_only:
            query += " and is_active = true"

        if search:
            query += " and (legal_name ilike :search or coalesce(nickname, '') ilike :search or coalesce(phone, '') ilike :search)"
            params["search"] = f"%{search.strip()}%"

        query += " order by legal_name asc"
        rows = self.db.execute(text(query), params).mappings().all()
        return {"items": [dict(r) for r in rows]}

    def create(self, company_id: str | None, payload: PartyCreate) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)
        party_type = payload.party_type.strip().lower()
        if party_type not in ALLOWED_PARTY_TYPES:
            raise HTTPException(status_code=422, detail="Invalid party_type")

        row = self.db.execute(
            text(
                """
                insert into parties (
                    company_id,
                    party_type,
                    nickname,
                    legal_name,
                    contact_person,
                    phone,
                    email,
                    address,
                    gst_number
                ) values (
                    :company_id,
                    :party_type,
                    :nickname,
                    :legal_name,
                    :contact_person,
                    :phone,
                    :email,
                    :address,
                    :gst_number
                )
                returning
                    id,
                    company_id,
                    party_type,
                    nickname,
                    legal_name,
                    contact_person,
                    phone,
                    email,
                    address,
                    gst_number,
                    is_active
                """
            ),
            {
                "company_id": resolved_company_id,
                "party_type": party_type,
                "nickname": payload.nickname,
                "legal_name": payload.legal_name.strip(),
                "contact_person": payload.contact_person,
                "phone": payload.phone,
                "email": payload.email,
                "address": payload.address,
                "gst_number": payload.gst_number,
            },
        ).mappings().first()
        self.db.commit()

        if not row:
            raise HTTPException(status_code=500, detail="Failed to create party")
        return dict(row)

    def update(self, party_id: str, payload: PartyUpdate, company_id: str | None) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)

        current = self.db.execute(
            text(
                """
                select id, company_id, party_type, nickname, legal_name, contact_person, phone, email, address, gst_number, is_active
                from parties
                where id = :party_id and company_id = :company_id
                """
            ),
            {"party_id": party_id, "company_id": resolved_company_id},
        ).mappings().first()

        if not current:
            raise HTTPException(status_code=404, detail="Party not found")

        values = dict(current)
        changes = payload.model_dump(exclude_unset=True)
        if "party_type" in changes and changes["party_type"] is not None:
            normalized = str(changes["party_type"]).strip().lower()
            if normalized not in ALLOWED_PARTY_TYPES:
                raise HTTPException(status_code=422, detail="Invalid party_type")
            changes["party_type"] = normalized
        if "legal_name" in changes and changes["legal_name"] is not None:
            changes["legal_name"] = str(changes["legal_name"]).strip()

        values.update(changes)

        updated = self.db.execute(
            text(
                """
                update parties
                set
                    party_type = :party_type,
                    nickname = :nickname,
                    legal_name = :legal_name,
                    contact_person = :contact_person,
                    phone = :phone,
                    email = :email,
                    address = :address,
                    gst_number = :gst_number,
                    is_active = :is_active,
                    updated_at = now()
                where id = :party_id and company_id = :company_id
                returning
                    id,
                    company_id,
                    party_type,
                    nickname,
                    legal_name,
                    contact_person,
                    phone,
                    email,
                    address,
                    gst_number,
                    is_active
                """
            ),
            {
                "party_id": party_id,
                "company_id": resolved_company_id,
                "party_type": values["party_type"],
                "nickname": values["nickname"],
                "legal_name": values["legal_name"],
                "contact_person": values["contact_person"],
                "phone": values["phone"],
                "email": values["email"],
                "address": values["address"],
                "gst_number": values["gst_number"],
                "is_active": values["is_active"],
            },
        ).mappings().first()

        self.db.commit()
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update party")
        return dict(updated)
