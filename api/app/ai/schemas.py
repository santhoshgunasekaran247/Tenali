from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def unique_attachments(self):
        if len(set(self.attachment_ids)) != len(self.attachment_ids):
            raise ValueError("Do not attach the same file twice")
        return self


class AIUpload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    file_name: str = Field(min_length=1, max_length=200)
    mime_type: Literal["text/plain", "application/pdf", "image/png", "image/jpeg", "image/webp"]
    data_base64: str = Field(min_length=1, max_length=4 * ((2 * 1024 * 1024 + 2) // 3))

class VoiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client_key: UUID
    language: Literal["auto", "en", "ta"] = "auto"
    data_base64: str = Field(min_length=1, max_length=4 * ((12 * 1024 * 1024 + 2) // 3))


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


CapabilityKey = Literal[
    "stores", "products", "parties", "hsn", "brands", "categories",
    "accounts", "transactions", "invoices", "purchases", "receivables",
    "refunds", "borrowings", "reorder", "reconciliation", "period_locks",
    "borrowing_entries", "stock_transfers", "stock_movements", "movement_sources", "variants",
    "vendor_offers", "collection_reminders", "reminder_history", "account_journal", "audit_events", "product_details",
    "business_payments",
]
CATALOGUE_KEYS = {"stores", "products", "parties", "hsn", "brands", "categories"}
STORE_READ_KEYS = {"products", "invoices", "purchases", "receivables", "refunds", "reorder", "reconciliation",
                   "stock_transfers", "stock_movements", "movement_sources", "collection_reminders", "reminder_history"}
COMPANY_LEDGER_KEYS = {"accounts", "transactions", "borrowings", "borrowing_entries", "account_journal", "audit_events", "business_payments"}
DATED_READ_KEYS = {"transactions", "invoices", "purchases", "receivables", "refunds", "period_locks",
                  "borrowing_entries", "stock_transfers", "stock_movements", "movement_sources",
                  "reminder_history", "account_journal", "audit_events", "business_payments"}
AS_OF_READ_KEYS = {"accounts", "period_locks", "collection_reminders"}
READ_STATUSES = {
    "invoices": {"UNPAID", "PARTIAL", "SETTLED", "BAD_DEBT", "CANCELLED"},
    "purchases": {"UNPAID", "PARTIAL", "PAID", "CANCELLED"},
    "receivables": {"UNPAID", "PARTIAL", "SETTLED", "BAD_DEBT"},
    "refunds": {"PENDING", "SETTLED"},
}


class LookupArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=2, max_length=80)
    store_id: UUID | None
    limit: int = Field(ge=1, le=10)


class BusinessLookupArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(max_length=80)
    store_id: UUID | None
    limit: int = Field(ge=1, le=10)
    from_date: date | None
    to_date: date | None
    as_of: date | None
    status: str | None = Field(max_length=20)

    @model_validator(mode="after")
    def date_range(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date cannot be after to_date")
        if self.query and len(self.query) < 2:
            raise ValueError("Use at least two characters for a search")
        return self


class ReadLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: CapabilityKey
    arguments: LookupArguments | BusinessLookupArguments

    @model_validator(mode="after")
    def capability_arguments(self):
        args = self.arguments
        if (self.capability in CATALOGUE_KEYS) != isinstance(args, LookupArguments):
            raise ValueError("Use the argument schema for this capability")
        if args.store_id and self.capability not in STORE_READ_KEYS:
            raise ValueError("This capability does not accept a store filter")
        if isinstance(args, BusinessLookupArguments):
            if (args.from_date or args.to_date) and self.capability not in DATED_READ_KEYS:
                raise ValueError("This capability does not accept date-range filters")
            if args.as_of and self.capability not in AS_OF_READ_KEYS:
                raise ValueError("This capability does not support historical as_of values")
            if args.status is not None and args.status not in READ_STATUSES.get(self.capability, set()):
                raise ValueError("Invalid status for this capability")
        return self


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
