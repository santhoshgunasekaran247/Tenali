from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class ReceivableCreate(BaseModel):
    party_id: UUID
    invoice_id: UUID | None = None
    reference: str | None = None
    amount_due: float
    due_date: date | None = None
    reminder_date: date | None = None
    notes: str | None = None


class ReceivableOut(BaseModel):
    id: UUID
    company_id: UUID
    party_id: UUID
    party_name: str
    invoice_id: UUID | None = None
    reference: str | None = None
    amount_due: float
    amount_received: float
    balance_amount: float
    status: str
    due_date: date | None = None
    reminder_date: date | None = None
    bad_debt_reason: str | None = None
    notes: str | None = None
    created_at: datetime


class ReceivableListResponse(BaseModel):
    items: list[ReceivableOut]


class ReceivablePaymentCreate(BaseModel):
    amount: float
    account_id: UUID
    payment_mode: str
    idempotency_key: str
    reference: str | None = None
    payment_date: date | None = None
    notes: str | None = None


class ReceivablePaymentOut(BaseModel):
    id: UUID
    receivable_id: UUID
    company_id: UUID
    account_id: UUID | None = None
    amount: float
    payment_mode: str
    idempotency_key: str | None = None
    reference: str | None = None
    payment_date: date
    notes: str | None = None
    created_at: datetime


class ReceivableStatusUpdate(BaseModel):
    status: str
    bad_debt_reason: str | None = None
    reminder_date: date | None = None


class ReminderListResponse(BaseModel):
    items: list[ReceivableOut]


class ReceivableReminderUpdate(BaseModel):
    next_reminder_date: date | None = None
    notes: str | None = None
    reminded_by: str | None = None


class ReceivableReminderLogOut(BaseModel):
    id: UUID
    receivable_id: UUID
    company_id: UUID
    reminder_date: date | None = None
    next_reminder_date: date | None = None
    reminded_at: datetime
    reminded_by: str | None = None
    notes: str | None = None


class ReceivableReminderLogListResponse(BaseModel):
    items: list[ReceivableReminderLogOut]
