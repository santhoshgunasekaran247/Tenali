from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PolicyKind = Literal["privacy", "terms", "shipping", "payment", "returns", "data-deletion", "contact"]
PolicyScope = Literal["platform", "tenant"]


class PolicyContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=160)
    business_name: str = Field(max_length=200)
    address: str = Field(max_length=1500)
    contact_email: str = Field(max_length=254)
    jurisdiction: str = Field(max_length=200)
    body: str = Field(min_length=1, max_length=50000)
    currency: Literal["INR"] = "INR"


class PolicySave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    content: PolicyContent


class PolicyPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(gt=0)
    reviewed: bool
