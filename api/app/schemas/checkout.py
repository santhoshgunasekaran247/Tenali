from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.services.tenant_security import Registration


class ShopperRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    display_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=12, max_length=128)
    _email = field_validator("email")(Registration.clean_email.__func__)
    _name = field_validator("display_name")(Registration.clean_name.__func__)


class DeliveryAddress(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=150)
    phone: str = Field(pattern=r"^[6-9][0-9]{9}$")
    address: str = Field(min_length=5, max_length=250)
    city: str = Field(min_length=1, max_length=80)
    state: str = Field(min_length=1, max_length=80)
    pincode: str = Field(pattern=r"^[1-9][0-9]{5}$")
    country: Literal["India"] = "India"


class CartItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    variant_id: UUID | None = None
    quantity: int = Field(ge=1, le=100, strict=True)


class CheckoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    items: list[CartItem] = Field(min_length=1, max_length=30)
    address: DeliveryAddress
    payment_method: Literal["prepaid", "cod", "pay_at_pickup"] = "prepaid"
    fulfilment_method: Literal["delivery", "pickup"] = "delivery"
    pickup_store_id: UUID | None = None
    expected_total_paise: int | None = Field(default=None, gt=0, le=100_000_000, strict=True)

    @field_validator("pickup_store_id")
    @classmethod
    def pickup_requires_store(cls, value, info):
        if info.data.get("fulfilment_method") == "pickup" and value is None:
            raise ValueError("Choose a pickup store")
        if info.data.get("fulfilment_method") == "delivery" and value is not None:
            raise ValueError("Delivery orders do not have a pickup store")
        return value


class EnquiryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    product_id: UUID
    variant_id: UUID | None = None
    quantity: int = Field(default=1, ge=1, le=1000, strict=True)
    store_id: UUID | None = None
    shopper_name: str = Field(min_length=1, max_length=120)
    shopper_phone: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")
    message: str | None = Field(default=None, max_length=1000)


class EnquiryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["open", "quoted", "converted", "closed"]
    invoice_id: UUID | None = None


class CodDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str | None = Field(default=None, max_length=500)


class DispatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ship_from_store_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=500)


class CollectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    account_id: UUID | None = None
    payment_mode: str | None = Field(default=None, min_length=1, max_length=40)


class OrderCancel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=500)
    refund_account_id: UUID | None = None


class CodSettlementItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: UUID
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)


class CodSettlementInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    courier: str = Field(min_length=1, max_length=80)
    settlement_reference: str = Field(min_length=1, max_length=120)
    settlement_date: date
    account_id: UUID
    items: list[CodSettlementItem] = Field(min_length=1, max_length=500)
    shortfall_reason: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("items")
    @classmethod
    def distinct_orders(cls, value):
        if len({item.order_id for item in value}) != len(value):
            raise ValueError("Each order may appear once per settlement")
        return value


class PaymentConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    razorpay_order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=100)
    razorpay_payment_id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$", max_length=100)
    razorpay_signature: str = Field(pattern=r"^[a-f0-9]{64}$")


class CheckoutSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    enabled: bool = False
    shipping_paise: int = Field(ge=0, le=1_000_000, strict=True)
    pickup_location: str = Field(default="", max_length=100)
    prepaid_enabled: bool = True
    shipping_sac: str = Field(default="9968", pattern=r"^\d{4,8}$")
    shipping_gst_rate: Decimal = Field(default=Decimal("18"), ge=0, le=100, max_digits=5, decimal_places=2)
    cod_enabled: bool = False
    cod_limit: Decimal = Field(default=Decimal("5000"), ge=0, max_digits=14, decimal_places=2)
    cod_approval_hours: int = Field(default=24, ge=1, le=720)
    cod_overdue_days: int = Field(default=15, ge=1, le=365)
    cod_serviceable_pincodes: list[str] = Field(default_factory=list, max_length=5000)
    pickup_enabled: bool = False
    pickup_hold_hours: int = Field(default=72, ge=1, le=720)
    pickup_reminder_hours: int = Field(default=48, ge=1, le=720)
    prepaid_hold_minutes: int = Field(default=20, ge=5, le=180)

    @field_validator("cod_serviceable_pincodes")
    @classmethod
    def clean_pincodes(cls, value):
        cleaned = sorted({item.strip() for item in value if item and item.strip()})
        if any(not (len(item) == 6 and item.isdigit() and item[0] != "0") for item in cleaned):
            raise ValueError("Pincodes must be six digits")
        return cleaned
    razorpay_key_id: str | None = Field(default=None, pattern=r"^rzp_(test|live)_[A-Za-z0-9]+$", max_length=100)
    razorpay_key_secret: SecretStr | None = Field(default=None, min_length=1, max_length=256)
    razorpay_webhook_secret: SecretStr | None = Field(default=None, min_length=16, max_length=256)
    shiprocket_email: str | None = Field(default=None, max_length=254)
    shiprocket_password: SecretStr | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("shiprocket_email")
    @classmethod
    def clean_provider_email(cls, value: str | None):
        return Registration.clean_email(value) if value is not None else None


class PackageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weight: Decimal = Field(gt=0, le=1000, allow_inf_nan=False)
    length: Decimal = Field(gt=0, le=500, allow_inf_nan=False)
    width: Decimal = Field(gt=0, le=500, allow_inf_nan=False)
    height: Decimal = Field(gt=0, le=500, allow_inf_nan=False)


class ShipmentReconcile(BaseModel):
    provider_order_id: int = Field(gt=0, strict=True)
