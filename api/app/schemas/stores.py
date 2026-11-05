from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

StoreCode = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9]{2,8}$")]
StateCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{2}$")]
Pincode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[1-9][0-9]{5}$")]
E164 = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+[1-9][0-9]{7,14}$")]
Gstin = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True,
                                         pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")]


class StoreInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    code: StoreCode
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["offline", "warehouse", "online"]
    fulfilment_store_id: UUID | None = None
    allows_pickup: bool = False
    address: str | None = Field(default=None, max_length=1000)
    state_code: StateCode | None = None
    pincode: Pincode | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    gst_number: Gstin | None = None
    whatsapp_number: E164 | None = None
    settlement_account_id: UUID | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def check_kind_rules(self):
        if self.kind == "online":
            if not self.fulfilment_store_id:
                raise ValueError("An online store needs a fulfilment warehouse or shop")
            if self.allows_pickup:
                raise ValueError("An online store cannot be a pickup location")
        elif self.fulfilment_store_id:
            raise ValueError("Only online stores have a fulfilment store")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both latitude and longitude or neither")
        return self


class StoreOut(BaseModel):
    id: UUID
    company_id: UUID
    code: str
    invoice_code: str
    name: str
    kind: str
    holds_stock: bool
    fulfilment_store_id: UUID | None
    allows_pickup: bool
    address: str | None
    state_code: str | None
    pincode: str | None
    latitude: float | None
    longitude: float | None
    gst_number: str | None
    whatsapp_number: str | None
    settlement_account_id: UUID | None
    is_default: bool
    is_active: bool


class StoreListResponse(BaseModel):
    items: list[StoreOut]
