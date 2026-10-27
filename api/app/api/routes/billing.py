from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.billing import (
    InvoiceCreate,
    InvoiceListResponse,
    InvoiceOut,
    InvoiceReconcileResponse,
    InvoiceReconcileRunListResponse,
)
from app.services.billing_service import BillingService

router = APIRouter()


@router.get("/invoices", response_model=InvoiceListResponse)
def list_invoices(
    company_id: str | None = None,
    collection_status: str | None = None,
    db: Session = Depends(get_db),
):
    service = BillingService(db)
    return service.list_invoices(company_id=company_id, collection_status=collection_status)


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create_invoice(
    payload: InvoiceCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = BillingService(db)
    return service.create_invoice(company_id=company_id, payload=payload)


@router.post("/invoices/reconcile", response_model=InvoiceReconcileResponse)
def reconcile_invoices(
    company_id: str | None = None,
    triggered_by: str | None = None,
    db: Session = Depends(get_db),
):
    service = BillingService(db)
    return service.reconcile_invoices(company_id=company_id, triggered_by=triggered_by)


@router.get("/invoices/reconcile-runs", response_model=InvoiceReconcileRunListResponse)
def list_reconcile_runs(
    company_id: str | None = None,
    limit: int = 10,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    service = BillingService(db)
    return service.list_reconcile_runs(company_id=company_id, limit=limit, offset=offset)


@router.get("/invoices/reports/sales-register/export")
def export_sales_register_csv(
    company_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
):
    service = BillingService(db)
    csv_data = service.export_sales_register_csv(
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
    )
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sales_register.csv"'},
    )
