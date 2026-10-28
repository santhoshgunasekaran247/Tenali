from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.documents import AttachmentCreate, MAX_ATTACHMENTS


class AccountOut(BaseModel):
    id: UUID
    company_id: UUID
    nickname: str
    account_type: str
    party_id: UUID | None = None
    holder_name: str | None = None
    phone: str | None = None
    email: str | None = None
    opening_balance: float
    is_company_account: bool
    is_active: bool


class AccountCreate(BaseModel):
    nickname: str
    account_type: str
    party_id: UUID | None = None
    holder_name: str | None = None
    phone: str | None = None
    email: str | None = None
    opening_balance: float = 0
    is_company_account: bool = False


class AccountUpdate(BaseModel):
    nickname: str | None = None
    account_type: str | None = None
    party_id: UUID | None = None
    holder_name: str | None = None
    phone: str | None = None
    email: str | None = None
    opening_balance: float | None = None
    is_company_account: bool | None = None
    is_active: bool | None = None


class AccountListResponse(BaseModel):
    items: list[AccountOut]


class AccountTransactionOut(BaseModel):
    id: UUID
    company_id: UUID
    from_account_id: UUID | None = None
    from_account_name: str | None = None
    to_account_id: UUID | None = None
    to_account_name: str | None = None
    direction: str | None = None
    amount: float
    payment_mode: str | None = None
    reference: str | None = None
    category: str | None = None
    description: str | None = None
    transaction_date: date
    source_type: str | None = None
    source_id: UUID | None = None
    reversal_of_transaction_id: UUID | None = None
    is_reversed: bool = False
    created_at: datetime


class AccountTransactionCreate(BaseModel):
    from_account_id: UUID | None = None
    to_account_id: UUID | None = None
    amount: float
    payment_mode: str | None = None
    reference: str | None = None
    category: str | None = None
    description: str | None = None
    transaction_date: date | None = None


class AccountTransactionListResponse(BaseModel):
    items: list[AccountTransactionOut]


class AccountTallyRowOut(BaseModel):
    account_id: UUID
    account_name: str
    account_type: str
    is_company_account: bool
    opening_balance: float
    total_inflow: float
    total_outflow: float
    current_balance: float
    transaction_count: int
    last_transaction_date: date | None = None


class AccountTallyResponse(BaseModel):
    as_of: date
    total_opening_balance: float
    total_inflow: float
    total_outflow: float
    total_current_balance: float
    items: list[AccountTallyRowOut]


class AuditJournalEntryOut(BaseModel):
    transaction_id: UUID
    transaction_date: date
    period_key: str
    direction: str
    amount: float
    from_account_id: UUID | None = None
    from_account_name: str | None = None
    to_account_id: UUID | None = None
    to_account_name: str | None = None
    payment_mode: str | None = None
    reference: str | None = None
    category: str | None = None
    description: str | None = None
    source_type: str | None = None
    source_id: UUID | None = None
    reversal_of_transaction_id: UUID | None = None
    is_reversed: bool = False
    created_at: datetime


class AuditJournalBucketOut(BaseModel):
    period_key: str
    entry_count: int
    total_inflow: float
    total_outflow: float
    total_transfer: float
    net_flow: float


class AuditJournalResponse(BaseModel):
    period: str
    from_date: date
    to_date: date
    items: list[AuditJournalEntryOut]
    buckets: list[AuditJournalBucketOut]


class BusinessPaymentCreate(BaseModel):
    idempotency_key: str | None = Field(default=None,min_length=8,max_length=120)
    from_account_id: UUID
    amount: float
    purpose: str
    related_party_id: UUID | None = None
    payment_mode: str | None = None
    reference: str | None = None
    notes: str | None = None
    transaction_date: date | None = None
    create_borrowing: bool = True
    attachments: list[AttachmentCreate] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)


class BusinessPaymentOut(BaseModel):
    account_transaction: AccountTransactionOut
    borrowing_id: UUID | None = None


class TransactionReverseCreate(BaseModel):
    transaction_date: date | None = None
    reference: str | None = None
    notes: str | None = None


class TransactionReverseOut(BaseModel):
    original_transaction: AccountTransactionOut
    reversal_transaction: AccountTransactionOut


class PeriodLockCreate(BaseModel):
    period_start: date
    period_end: date
    reason: str | None = None
    closed_by: str | None = None


class PeriodLockReopen(BaseModel):
    reopened_by: str | None = None
    reopen_reason: str | None = None


class PeriodLockOut(BaseModel):
    id: UUID
    company_id: UUID
    period_start: date
    period_end: date
    reason: str | None = None
    closed_by: str | None = None
    is_active: bool
    created_at: datetime
    reopened_at: datetime | None = None
    reopened_by: str | None = None
    reopen_reason: str | None = None


class PeriodLockListResponse(BaseModel):
    items: list[PeriodLockOut]
