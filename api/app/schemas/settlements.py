from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class BorrowingEntryCreate(BaseModel):
    party_id: UUID
    direction: str
    amount: float
    transaction_date: date | None = None
    account_id: UUID | None = None
    reference: str | None = None
    notes: str | None = None
    create_account_transaction: bool = True


class BorrowingEntryOut(BaseModel):
    id: UUID
    company_id: UUID
    party_id: UUID
    party_name: str
    direction: str
    amount: float
    transaction_date: date
    account_id: UUID | None = None
    reference: str | None = None
    notes: str | None = None
    created_at: datetime


class BorrowingListResponse(BaseModel):
    items: list[BorrowingEntryOut]


class BorrowingSummaryOut(BaseModel):
    party_id: UUID
    party_name: str
    borrowed_amount: float
    repaid_amount: float
    net_outstanding: float


class BorrowingSummaryResponse(BaseModel):
    items: list[BorrowingSummaryOut]
