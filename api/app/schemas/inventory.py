from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.company import validate_image_source

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Quantity = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]


class ItemDetails(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    item_name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=6000)
    size: str | None = Field(default=None, max_length=100)
    colour: str | None = Field(default=None, max_length=100)
    weight: Quantity | None = None
    height: Quantity | None = None
    width: Quantity | None = None
    length: Quantity | None = None
    attributes: dict[str, Annotated[str, Field(max_length=500)]] = Field(default_factory=dict, max_length=40)
    sku: str | None = Field(default=None, max_length=100)
    pricing_mode: Literal["price", "discount"] = "price"
    selling_price: Money | None = None
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=2)
    preferred_vendor_id: UUID | None = None
    reorder_level: Quantity = Decimal("0")
    reorder_target: Quantity = Decimal("0")
    reorder_enabled: bool = False
    reorder_reminder_date: date | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_reorder(self):
        if self.reorder_enabled and self.reorder_target < self.reorder_level:
            raise ValueError("Reorder target must be at least the reorder threshold")
        return self


class ProductInput(ItemDetails):
    name: str = Field(min_length=1, max_length=200)
    brand_id: UUID | None = None
    category_id: UUID | None = None
    hsn_code: str | None = Field(default=None, pattern=r"^(?:\d{4}|\d{6}|\d{8})$")
    image_url: str | None = Field(default=None, max_length=1400000)
    image_urls: list[str] = Field(default_factory=list, max_length=12)
    catalog_visible: bool = True
    best_seller: bool = False
    sru_special: bool = False
    home_order: int = Field(default=999, ge=0, le=99999)

    @model_validator(mode="after")
    def validate_images(self):
        validate_image_source(self.image_url)
        for image in self.image_urls:
            validate_image_source(image)
        return self


class VariantInput(ItemDetails):
    variant_name: str = Field(min_length=1, max_length=200)
    pricing_mode: Literal["price", "discount", "inherit"] = "inherit"


class VendorOfferInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    vendor_id: UUID
    variant_id: UUID | None = None
    mrp: Money | None = None
    buying_price: Money | None = None
    available_quantity: Quantity = Decimal("0")
    availability: Literal["AVAILABLE", "OUT_OF_STOCK", "ON_ORDER", "UNKNOWN"] = "UNKNOWN"
    lead_time_days: int = Field(default=0, ge=0, le=3650)
    sku: str | None = Field(default=None, max_length=100)
    vendor_reference: str | None = Field(default=None, max_length=300)
    vendor_product_url: str | None = Field(default=None, max_length=1000)
    is_active: bool = True


class BulkVendorMapping(BaseModel):
    vendor_id: UUID
    product_ids: list[UUID] = Field(min_length=1, max_length=200)


class StockAdjustment(BaseModel):
    idempotency_key: str | None = Field(default=None,min_length=8,max_length=120)
    variant_id: UUID | None = None
    direction: Literal["IN", "OUT"]
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    notes: str = Field(min_length=1, max_length=1000)


class ReorderReminder(BaseModel):
    variant_id: UUID | None = None
    reminder_date: date


class InventoryLookupCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="",max_length=2000)
    is_active: bool = True