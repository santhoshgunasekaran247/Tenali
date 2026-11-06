from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.billing import InvoiceLineCreate
from app.schemas.common import SubmissionKey
from app.schemas.documents import AttachmentCreate, MAX_ATTACHMENTS
from app.schemas.money import Money, PositiveMoney


class PurchaseCreate(BaseModel):
    idempotency_key: str | None = Field(default=None,min_length=8,max_length=120)
    store_id: UUID | None = None
    vendor_party_id: UUID
    purchase_date: date | None = None
    bill_number: str | None = None
    subtotal: Money = Decimal("0")
    gst_total: Money = Decimal("0")
    total: Money | None = None
    amount_paid: Money = Decimal("0")
    payment_mode: str | None = None
    account_id: UUID | None = None
    reference: str | None = None
    due_date: date | None = None
    notes: str | None = None
    receipt_type: str = "PRODUCT"
    # True books the goods into stock as part of posting instead of waiting for a separate receipt.
    received_now: bool = False
    lines: list[InvoiceLineCreate] = Field(default_factory=list, max_length=200)
    attachments: list[AttachmentCreate] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)


class PurchaseOut(BaseModel):
    id: UUID
    company_id: UUID
    store_id: UUID | None = None
    store_code: str | None = None
    voucher_number: str | None = None
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
    amount: PositiveMoney
    account_id: UUID
    payment_mode: str
    idempotency_key: SubmissionKey
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
