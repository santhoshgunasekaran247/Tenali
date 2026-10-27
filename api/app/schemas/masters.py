from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HsnMasterCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str = Field(pattern=r"^(?:\d{4}|\d{6}|\d{8})$")
    description: str = Field(min_length=1, max_length=300)
    gst_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    is_active: bool = True


class HsnMasterUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    description: str = Field(min_length=1, max_length=300)
    gst_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    is_active: bool


class HsnMasterOut(HsnMasterCreate):
    gst_rate: float
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime


class HsnMasterListResponse(BaseModel):
    items: list[HsnMasterOut]