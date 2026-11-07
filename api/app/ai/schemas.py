from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["active", "archived"] | None = None
    expected_version: int = Field(ge=1)


class ConversationOut(BaseModel):
    id: UUID
    title: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=4000)
    client_key: UUID


class MessageOut(BaseModel):
    id: UUID
    client_key: UUID
    role: Literal["user", "assistant"]
    content: str
    status: Literal["pending", "completed", "failed", "unknown"]
    error_code: str | None
    created_at: datetime


class AssistantOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply: str
    clarification: str | None


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    value: str = Field(min_length=1, max_length=500)


CapabilityKey = Literal["stores", "products", "parties", "hsn", "brands", "categories"]


class LookupArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=2, max_length=80)
    store_id: UUID | None
    limit: int = Field(ge=1, le=10)


class ReadLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: CapabilityKey
    arguments: LookupArguments


class ReadAssistantOutput(AssistantOutput):
    lookups: list[ReadLookup] = Field(max_length=2)


class CapabilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    approve_contract: bool = False
    expected_version: int = Field(ge=1)


class TenantCapabilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed: bool
    expected_version: int = Field(ge=0)
