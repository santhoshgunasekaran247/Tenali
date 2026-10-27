from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.settlements import (
    BorrowingEntryCreate,
    BorrowingEntryOut,
    BorrowingListResponse,
    BorrowingSummaryResponse,
)
from app.services.settlements_service import SettlementsService

router = APIRouter()


@router.get("/borrowings", response_model=BorrowingListResponse)
def list_borrowings(
    company_id: str | None = None,
    party_id: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    service = SettlementsService(db)
    return service.list_borrowings(company_id=company_id, party_id=party_id, limit=limit)


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
