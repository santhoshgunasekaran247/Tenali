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
    expected_total_paise: int | None = Field(default=None, gt=0, le=100_000_000, strict=True)


class PaymentConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    razorpay_order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=100)
    razorpay_payment_id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$", max_length=100)
    razorpay_signature: str = Field(pattern=r"^[a-f0-9]{64}$")


class CheckoutSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    enabled: bool = False
    shipping_paise: int = Field(ge=0, le=1_000_000, strict=True)
    pickup_location: str = Field(min_length=1, max_length=100)
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
