from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class InvoiceLineCreate(BaseModel):
    product_id: UUID | None = None
    variant_id: UUID | None = None
    description: str = Field(min_length=1, max_length=500)
    hsn: str = Field(pattern=r"^\d{4,8}$")
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    rate: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=5, decimal_places=2)


class InvoiceCreate(BaseModel):
    idempotency_key: str | None = Field(default=None,min_length=8,max_length=120)
    customer_party_id: UUID
    invoice_date: date | None = None
    subtotal: float = 0
    gst_total: float = 0
    total: float | None = None
    payment_mode: str | None = None
    account_id: UUID | None = None
    reference: str | None = None
    due_date: date | None = None
    reminder_date: date | None = None
    amount_received: float = 0
    notes: str | None = None
    auto_create_receivable: bool = True
    lines: list[InvoiceLineCreate] = Field(default_factory=list, max_length=200)
    billing_address: str | None = Field(default=None, max_length=2000)
    shipping_name: str | None = Field(default=None, max_length=300)
    shipping_address: str | None = Field(default=None, max_length=2000)
    place_of_supply: str | None = Field(default=None, pattern=r"^\d{2} - .+")


class InvoiceOut(BaseModel):
    id: UUID
    company_id: UUID
    invoice_number: str
    customer_party_id: UUID
    customer_name: str
    customer_gst: str | None = None
    invoice_date: date
    subtotal: float
    gst_total: float
    total: float
    payment_mode: str | None = None
    account_id: UUID | None = None
    reference: str | None = None
    status: str
    collection_status: str
    amount_received: float
    due_date: date | None = None
    reminder_date: date | None = None
    bad_debt_reason: str | None = None
    created_at: datetime
    document_data: dict | None = None


class InvoiceListResponse(BaseModel):
    items: list[InvoiceOut]


class InvoiceReconcileResponse(BaseModel):
    healed_count: int


class InvoiceReconcileRunOut(BaseModel):
    id: UUID
    company_id: UUID
    healed_count: int
    triggered_by: str | None = None
    created_at: datetime


class InvoiceReconcileRunListResponse(BaseModel):
    items: list[InvoiceReconcileRunOut]
    total: int
    limit: int
    offset: int
