from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.collections import (
    ReceivableCreate,
    ReceivableListResponse,
    ReceivableOut,
    ReceivablePaymentCreate,
    ReceivablePaymentOut,
    ReceivableReminderLogListResponse,
    ReceivableReminderUpdate,
    ReceivableStatusUpdate,
    ReminderListResponse,
)
from app.services.collections_service import CollectionsService

router = APIRouter()


@router.get("/receivables", response_model=ReceivableListResponse)
def list_receivables(
    company_id: str | None = None,
    status: str | None = None,
    open_only: bool = False,
    from_date: date | None = None,
    to_date: date | None = None,
    store_id: str | None = None,
    search: str = Query("", max_length=200),
    invoice_id: UUID | None = None,
    receivable_id: UUID | None = None,
    page_size: int | None = Query(None, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1000),
    db: Session = Depends(get_db),
):
    if cursor and page_size is None:
        raise HTTPException(422, "page_size is required with cursor")
    service = CollectionsService(db)
    return service.list_receivables(company_id=company_id, status=status, open_only=open_only, from_date=from_date, to_date=to_date, store_id=store_id, search=search, invoice_id=str(invoice_id) if invoice_id else None, receivable_id=str(receivable_id) if receivable_id else None, page_size=page_size, cursor=cursor)


@router.post("/receivables", response_model=ReceivableOut, status_code=201)
def create_receivable(
    payload: ReceivableCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = CollectionsService(db)
    return service.create_receivable(company_id=company_id, payload=payload)


@router.post("/receivables/{receivable_id}/payments", response_model=ReceivablePaymentOut, status_code=201)
def collect_receivable(
    receivable_id: str,
    payload: ReceivablePaymentCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = CollectionsService(db)
    return service.collect_receivable(
        receivable_id=receivable_id,
        company_id=company_id,
        payload=payload,
    )


@router.patch("/receivables/{receivable_id}", response_model=ReceivableOut)
def update_receivable_status(
    receivable_id: str,
    payload: ReceivableStatusUpdate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = CollectionsService(db)
    return service.update_receivable_status(
        receivable_id=receivable_id,
        company_id=company_id,
        payload=payload,
    )


@router.get("/receivables-reminders", response_model=ReminderListResponse)
def list_due_reminders(
    company_id: str | None = None,
    as_of: date | None = None,
    store_id: str | None = None,
    page_size: int | None = Query(None, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1000),
    db: Session = Depends(get_db),
):
    if cursor and page_size is None:
        raise HTTPException(422, "page_size is required with cursor")
    service = CollectionsService(db)
    return service.list_due_reminders(company_id=company_id, as_of=as_of, store_id=store_id, page_size=page_size, cursor=cursor)


@router.post("/receivables/{receivable_id}/remind", response_model=ReceivableOut)
def mark_receivable_reminder(
    receivable_id: str,
    payload: ReceivableReminderUpdate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = CollectionsService(db)
    return service.mark_reminder(
        receivable_id=receivable_id,
        company_id=company_id,
        payload=payload,
    )


@router.get("/receivables/{receivable_id}/reminders", response_model=ReceivableReminderLogListResponse)
def list_receivable_reminder_history(
    receivable_id: str,
    company_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    reminded_by: str | None = None,
    store_id: str | None = None,
    page_size: int | None = Query(None, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1000),
    db: Session = Depends(get_db),
):
    if cursor and page_size is None:
        raise HTTPException(422, "page_size is required with cursor")
    service = CollectionsService(db)
    return service.list_reminder_history(
        receivable_id=receivable_id,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        reminded_by=reminded_by,
        store_id=store_id,
        page_size=page_size,
        cursor=cursor,
    )


@router.get("/receivables/reports/ar-aging/export")
def export_ar_aging_csv(
    company_id: str | None = None,
    as_of: str | None = None,
    db: Session = Depends(get_db),
):
    service = CollectionsService(db)
    csv_data = service.export_ar_aging_csv(company_id=company_id, as_of=as_of)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="ar_aging.csv"'},
    )
