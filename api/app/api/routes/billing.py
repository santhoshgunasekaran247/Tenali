from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.billing import (
    InvoiceCreate,
    InvoiceListResponse,
    InvoiceOut,
    InvoiceReconcileResponse,
    InvoiceReconcileRunListResponse,
    QuotationCreate, QuotationOut, QuotationListResponse,
)
from app.services.billing_service import BillingService
from app.services.quotation_service import QuotationService
from app.services.document_cancellation import Cancellation,cancel_document
from app.schemas.parties import PartyCreate, PartyOut
from app.services.parties_service import PartiesService

router = APIRouter()


@router.get("/quotations", response_model=QuotationListResponse)
def list_quotations(company_id: str | None = None, store_id: str | None = None, db: Session = Depends(get_db)):
    return QuotationService(db).list(company_id, store_id)


@router.post("/quotations", response_model=QuotationOut, status_code=201)
def create_quotation(payload: QuotationCreate, company_id: str | None = None, db: Session = Depends(get_db)):
    return QuotationService(db).create(company_id, payload)


@router.get("/quotations/{quotation_id}", response_model=QuotationOut)
def get_quotation(quotation_id: UUID, company_id: str | None = None, db: Session = Depends(get_db)):
    items = QuotationService(db).list(company_id, quotation_id=str(quotation_id))["items"]
    if not items:
        raise HTTPException(404, "Quotation not found")
    return items[0]


@router.get("/customers")
def billing_customers(search: str | None = None, company_id: str | None = None, db: Session = Depends(get_db)):
    result = PartiesService(db).list(company_id, search, True)
    return {"items": [party for party in result["items"] if party["party_type"] in {"customer", "customer_vendor"}]}


@router.post("/customers", response_model=PartyOut, status_code=201)
def add_billing_customer(payload: PartyCreate, company_id: str | None = None, db: Session = Depends(get_db)):
    if payload.party_type != "customer":
        raise HTTPException(422, "Only customers can be created from billing")
    return PartiesService(db).create(company_id, payload)


@router.post("/invoices/{invoice_id}/cancel")
def cancel_invoice(invoice_id: str,payload:Cancellation,company_id:str|None=None,db:Session=Depends(get_db)):
    company=BillingService(db)._resolve_company_id(company_id)
    return cancel_document(db,company,"invoice",invoice_id,payload)


@router.get("/invoices", response_model=InvoiceListResponse)
def list_invoices(
    company_id: str | None = None,
    collection_status: str | None = None,
    store_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = BillingService(db)
    return service.list_invoices(company_id=company_id, collection_status=collection_status, store_id=store_id)


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


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: UUID, company_id: str | None = None, db: Session = Depends(get_db)):
    items = BillingService(db).list_invoices(company_id, invoice_id=str(invoice_id), limit=1)["items"]
    if not items:
        raise HTTPException(404, "Invoice not found")
    return items[0]
