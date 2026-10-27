from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.schemas.billing import InvoiceLineCreate
from app.schemas.masters import HsnMasterCreate, HsnMasterUpdate


class MastersService:
    def __init__(self, db: Session):
        self.db = db

    def _company_id(self, company_id: str | None) -> str:
        result = self.db.execute(text("""
            select id from companies where is_active = true
            and (cast(:id as uuid) is null or id = cast(:id as uuid))
            order by created_at asc, id asc limit 1
        """), {"id": company_id}).scalar_one_or_none()
        if not result:
            raise HTTPException(status_code=404, detail="Company not found")
        return str(result)

    def list_hsn(self, company_id: str | None, active_only: bool = True, search: str | None = None) -> dict:
        rows = self.db.execute(text("""
            select * from hsn_masters where company_id = :company_id
            and (not :active_only or is_active = true)
            and (:search = '' or code ilike :pattern or description ilike :pattern)
            order by code asc
        """), {"company_id": self._company_id(company_id), "active_only": active_only,
                "search": search or "", "pattern": f"%{search or ''}%"}).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def create_hsn(self, payload: HsnMasterCreate, company_id: str | None) -> dict:
        values = {**payload.model_dump(), "company_id": self._company_id(company_id)}
        try:
            row = self.db.execute(text("""
                insert into hsn_masters(company_id, code, description, gst_rate, is_active)
                values(:company_id, :code, :description, :gst_rate, :is_active) returning *
            """), values).mappings().one()
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="HSN/SAC code already exists; edit or reactivate it") from exc
        return dict(row)

    def update_hsn(self, master_id: str, payload: HsnMasterUpdate, company_id: str | None) -> dict:
        row = self.db.execute(text("""
            update hsn_masters set description = :description, gst_rate = :gst_rate,
                is_active = :is_active, updated_at = now()
            where id = :id and company_id = :company_id returning *
        """), {**payload.model_dump(), "id": master_id, "company_id": self._company_id(company_id)}).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="HSN/SAC code not found")
        self.db.commit()
        return dict(row)

    def apply_hsn_rates(self, lines: list[InvoiceLineCreate], company_id: str) -> None:
        if not lines:
            return
        codes = sorted({line.hsn for line in lines})
        rows = self.db.execute(text("""
            select code, gst_rate from hsn_masters
            where company_id = :company_id and is_active = true and code in :codes
            for share
        """).bindparams(bindparam("codes", expanding=True)),
            {"company_id": company_id, "codes": codes}).mappings().all()
        rates = {row["code"]: Decimal(str(row["gst_rate"])) for row in rows}
        missing = [code for code in codes if code not in rates]
        if missing:
            raise HTTPException(status_code=422, detail=f"Select active HSN/SAC codes from Master Data: {', '.join(missing)}")
        for line in lines:
            line.gst_rate = rates[line.hsn]