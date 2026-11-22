from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.settlements import (
    BorrowingEntryCreate,
    BorrowingEntryOut,
    BorrowingListResponse,
    BorrowingSummaryResponse,
)
from app.services.refund_settlements import RefundSettle, RefundSettlementsService
from app.services.settlements_service import SettlementsService

router = APIRouter()


@router.get("/refunds")
def list_refunds(status: str | None = None, page_size: int | None = Query(None, ge=1, le=100),
                 cursor: str | None = Query(None, max_length=1000), from_date: date | None = None,
                 to_date: date | None = None, db: Session = Depends(get_db)):
    if cursor and page_size is None:
        raise HTTPException(422, "page_size is required with cursor")
    if from_date and to_date and from_date > to_date:
        raise HTTPException(422, "from_date cannot be after to_date")
    return RefundSettlementsService(db).list(status, page_size=page_size, cursor=cursor, from_date=from_date, to_date=to_date)


@router.post("/refunds/{settlement_id}/settle")
def settle_refund(settlement_id: UUID, payload: RefundSettle, db: Session = Depends(get_db)):
    return RefundSettlementsService(db).settle(str(settlement_id), payload)


@router.get("/borrowings", response_model=BorrowingListResponse)
def list_borrowings(
    company_id: str | None = None,
    party_id: str | None = None,
    limit: int = 200,
    from_date: date | None = None,
    to_date: date | None = None,
    page_size: int | None = Query(None, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1000),
    db: Session = Depends(get_db),
):
    if cursor and page_size is None:
        raise HTTPException(422, "page_size is required with cursor")
    if from_date and to_date and from_date > to_date:
        raise HTTPException(422, "from_date cannot be after to_date")
    service = SettlementsService(db)
    return service.list_borrowings(company_id=company_id, party_id=party_id, limit=limit,
                                   page_size=page_size, cursor=cursor, from_date=from_date, to_date=to_date)


@router.get("/borrowings/summary", response_model=BorrowingSummaryResponse)
def borrowing_summary(
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = SettlementsService(db)
    return service.summarize_borrowings(company_id=company_id)


@router.post("/borrowings", response_model=BorrowingEntryOut, status_code=201)
def create_borrowing(
    payload: BorrowingEntryCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = SettlementsService(db)
    return service.create_borrowing(company_id=company_id, payload=payload)
