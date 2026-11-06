from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.money import Money


class InvoiceLineCreate(BaseModel):
    product_id: UUID | None = None
    variant_id: UUID | None = None
    description: str = Field(min_length=1, max_length=500)
    hsn: str = Field(pattern=r"^\d{4,8}$")
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    rate: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=5, decimal_places=2)
    # None = the document default: sales lines are GST-inclusive, purchase lines exclusive.
    price_includes_gst: bool | None = None
    # Purchases only: add this line's item to Product Inventory as a draft product.
    new_product: bool = False


class InvoiceCreate(BaseModel):
    idempotency_key: str | None = Field(default=None,min_length=8,max_length=120)
    store_id: UUID | None = None
    # Online orders: the store whose stock is booked when it differs from the invoicing store's fulfilment store.
    stock_store_id: UUID | None = None
    customer_party_id: UUID
    invoice_date: date | None = None
    subtotal: Money = Decimal("0")
    gst_total: Money = Decimal("0")
    total: Money | None = None
    payment_mode: str | None = None
    account_id: UUID | None = None
    reference: str | None = None
    due_date: date | None = None
    reminder_date: date | None = None
    amount_received: Money = Decimal("0")
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
    store_id: UUID | None = None
    store_code: str | None = None
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
    cancelled_at: date | None = None
    cancellation_reason: str | None = None


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
