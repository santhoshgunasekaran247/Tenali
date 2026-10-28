from datetime import date

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.services.commerce_stock import book_stock
from app.services.period_lock_service import assert_period_open


class Cancellation(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)
    reason: str=Field(min_length=1,max_length=1000)
    cancellation_date: date | None=None


def cancel_document(db, company_id: str, kind: str, document_id: str, payload: Cancellation):
    table="invoices" if kind=="invoice" else "purchases"
    row=db.execute(text(f"select * from {table} where id=:id and company_id=:company for update"),{"id":document_id,"company":company_id}).mappings().first()
    if not row:
        raise HTTPException(404,"Document not found")
    if row["status"]=="CANCELLED":
        return {"id":document_id,"status":"CANCELLED"}
    paid=row["amount_received"] if kind=="invoice" else row["amount_paid"]
    if paid:
        raise HTTPException(422,"Reverse the document's payment transactions before cancellation; cancellation does not issue a refund")
    effective=payload.cancellation_date or date.today()
    source_date=row["invoice_date"] if kind=="invoice" else row["purchase_date"]
    if effective<source_date:
        raise HTTPException(422,"Cancellation cannot precede the document date")
    assert_period_open(db,company_id,effective,"Cancelling document")
    if kind=="invoice":
        lines=(row["document_data"] or {}).get("lines",[])
        book_stock(db,company_id,lines,"IN","invoice_cancellation",document_id)
        db.execute(text("update receivables set status='SETTLED',updated_at=now() where invoice_id=:id and company_id=:company"),{"id":document_id,"company":company_id})
    elif row["receipt_status"]=="RECEIVED" and row["receipt_type"]!="SERVICE":
        book_stock(db,company_id,row["line_items"],"OUT","purchase_cancellation",document_id)
    db.execute(text(f"update {table} set status='CANCELLED',cancelled_at=:date,cancellation_reason=:reason where id=:id"),{"date":effective,"reason":payload.reason,"id":document_id})
    db.commit()
    return {"id":document_id,"status":"CANCELLED"}