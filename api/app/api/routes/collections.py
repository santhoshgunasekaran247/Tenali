from datetime import date

from fastapi import APIRouter, Depends
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
    db: Session = Depends(get_db),
):
    service = CollectionsService(db)
    return service.list_receivables(company_id=company_id, status=status)


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
    db: Session = Depends(get_db),
):
    service = CollectionsService(db)
    return service.list_due_reminders(company_id=company_id, as_of=as_of)


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
    db: Session = Depends(get_db),
):
    service = CollectionsService(db)
    return service.list_reminder_history(
        receivable_id=receivable_id,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        reminded_by=reminded_by,
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
