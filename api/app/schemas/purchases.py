from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.billing import InvoiceLineCreate
from app.schemas.documents import AttachmentCreate, MAX_ATTACHMENTS


class PurchaseCreate(BaseModel):
    idempotency_key: str | None = Field(default=None,min_length=8,max_length=120)
    vendor_party_id: UUID
    purchase_date: date | None = None
    bill_number: str | None = None
    subtotal: float = 0
    gst_total: float = 0
    total: float | None = None
    amount_paid: float = 0
    payment_mode: str | None = None
    account_id: UUID | None = None
    reference: str | None = None
    due_date: date | None = None
    notes: str | None = None
    receipt_type: str = "PRODUCT"
    lines: list[InvoiceLineCreate] = Field(default_factory=list, max_length=200)
    attachments: list[AttachmentCreate] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)


class PurchaseOut(BaseModel):
    id: UUID
    company_id: UUID
    vendor_party_id: UUID
    vendor_name: str
    bill_number: str | None = None
    purchase_date: date
    subtotal: float
    gst_total: float
    total: float
    amount_paid: float
    balance_amount: float
    payment_status: str
    payment_mode: str | None = None
    account_id: UUID | None = None
    reference: str | None = None
    due_date: date | None = None
    notes: str | None = None
    receipt_type: str
    receipt_status: str
    received_at: datetime | None = None
    received_notes: str | None = None
    status: str
    created_at: datetime
    line_items: list[dict] = Field(default_factory=list)


class PurchaseListResponse(BaseModel):
    items: list[PurchaseOut]


class PurchasePaymentCreate(BaseModel):
    amount: float
    account_id: UUID
    payment_mode: str
    idempotency_key: str
    payment_date: date | None = None
    reference: str | None = None
    notes: str | None = None


class PurchasePaymentOut(BaseModel):
    id: UUID
    purchase_id: UUID
    company_id: UUID
    account_id: UUID
    amount: float
    payment_mode: str
    idempotency_key: str | None = None
    reference: str | None = None
    payment_date: date
    notes: str | None = None
    created_at: datetime


class PurchasePaymentListResponse(BaseModel):
    items: list[PurchasePaymentOut]


class PurchaseReceiptConfirm(BaseModel):
    receipt_type: str | None = None
    received_at: datetime | None = None
    received_notes: str | None = None
