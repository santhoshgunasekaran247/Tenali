from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.purchases import (
    PurchaseCreate,
    PurchaseListResponse,
    PurchaseOut,
    PurchasePaymentListResponse,
    PurchasePaymentCreate,
    PurchaseReceiptConfirm,
)
from app.services.purchases_service import PurchasesService
from app.services.document_cancellation import Cancellation,cancel_document

router = APIRouter()


@router.post("/{purchase_id}/cancel")
def cancel_purchase(purchase_id:str,payload:Cancellation,company_id:str|None=None,db:Session=Depends(get_db)):
    company=PurchasesService(db)._resolve_company_id(company_id)
    return cancel_document(db,company,"purchase",purchase_id,payload)


@router.get("", response_model=PurchaseListResponse)
def list_purchases(
    company_id: str | None = None,
    vendor_party_id: str | None = None,
    payment_status: str | None = None,
    db: Session = Depends(get_db),
):
    service = PurchasesService(db)
    return service.list_purchases(
        company_id=company_id,
        vendor_party_id=vendor_party_id,
        payment_status=payment_status,
    )


@router.post("", response_model=PurchaseOut, status_code=201)
def create_purchase(
    payload: PurchaseCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = PurchasesService(db)
    return service.create_purchase(company_id=company_id, payload=payload)


@router.post("/{purchase_id}/payments", response_model=PurchaseOut)
def add_purchase_payment(
    purchase_id: str,
    payload: PurchasePaymentCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = PurchasesService(db)
    return service.add_purchase_payment(
        purchase_id=purchase_id,
        company_id=company_id,
        payload=payload,
    )


@router.get("/{purchase_id}/payments", response_model=PurchasePaymentListResponse)
def list_purchase_payments(
    purchase_id: str,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = PurchasesService(db)
    return service.list_purchase_payments(
        purchase_id=purchase_id,
        company_id=company_id,
    )


@router.post("/{purchase_id}/confirm-receipt", response_model=PurchaseOut)
def confirm_purchase_receipt(
    purchase_id: str,
    payload: PurchaseReceiptConfirm,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = PurchasesService(db)
    return service.confirm_purchase_receipt(
        purchase_id=purchase_id,
        company_id=company_id,
        payload=payload,
    )


@router.get("/reports/purchase-register/export")
def export_purchase_register_csv(
    company_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
):
    service = PurchasesService(db)
    csv_data = service.export_purchase_register_csv(
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
    )
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="purchase_register.csv"'},
    )


@router.get("/reports/ap-aging/export")
def export_ap_aging_csv(
    company_id: str | None = None,
    as_of: str | None = None,
    db: Session = Depends(get_db),
):
    service = PurchasesService(db)
    csv_data = service.export_ap_aging_csv(company_id=company_id, as_of=as_of)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="ap_aging.csv"'},
    )
