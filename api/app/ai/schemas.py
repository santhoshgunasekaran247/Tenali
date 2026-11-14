from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Tenali businesses report in Indian time (INR/GST); chat periods use the business date, not the server clock.
BUSINESS_TZ = timezone(timedelta(hours=5, minutes=30))


def business_today():
    return datetime.now(BUSINESS_TZ).date()


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

    @model_validator(mode="before")
    @classmethod
    def short_query_shape(cls, data):
        # A catalogue-shaped request with an empty/1-char query can only be the business shape (no filters).
        args = data.get("arguments") if isinstance(data, dict) else None
        if (isinstance(args, dict) and data.get("capability") in CATALOGUE_KEYS and isinstance(args.get("status"), str)
                and not (args.get("from_date") or args.get("to_date") or args.get("as_of"))):
            # Catalogues have no status filter; a word placed there ("vendor") describes what to find.
            args = {**args, "query": f"{args.get('query') or ''} {args['status']}".strip()[:80], "status": None}
            data = {**data, "arguments": args}
        if (isinstance(args, dict) and args.get("as_of") is not None and data.get("capability") not in AS_OF_READ_KEYS
                and str(args["as_of"]) == business_today().isoformat()):
            # "As of today" is the current state these reads already return; only historical as_of is unsupported.
            args = {**args, "as_of": None}
            data = {**data, "arguments": args}
        if isinstance(args, dict) and isinstance(args.get("query"), str) and len(args["query"].strip()) < 2:
            data = {**data, "arguments": {"from_date": None, "to_date": None, "as_of": None, "status": None, **args}}
        return data

    @model_validator(mode="after")
    def capability_arguments(self):
        args = self.arguments
        if (isinstance(args, BusinessLookupArguments) and args.status is None
                and args.query.strip().upper().replace(" ", "_") in READ_STATUSES.get(self.capability, set())):
            # "unpaid invoices" is a status filter, not text to search for.
            args = self.arguments = args.model_copy(update={"status": args.query.strip().upper().replace(" ", "_"), "query": ""})
        if (self.capability == "products" and isinstance(args, BusinessLookupArguments) and not args.query
                and not (args.from_date or args.to_date or args.as_of or args.status is not None)):
            # Product search needs a name; an unnamed stock question is the per-store balance listing.
            self.capability = "reconciliation"
        elif (self.capability in CATALOGUE_KEYS and isinstance(args, BusinessLookupArguments)
                and not (args.from_date or args.to_date or args.as_of or args.status is not None)):
            # Models often send the shared nullable filter shape; keep only catalogue fields.
            # An empty catalogue query is a bounded listing ("who are my vendors"); adapters accept it.
            values = {"query": args.query, "store_id": args.store_id, "limit": args.limit}
            args = self.arguments = LookupArguments.model_construct(**values) if not args.query else LookupArguments(**values)
        elif self.capability not in CATALOGUE_KEYS and isinstance(args, LookupArguments):
            # The short catalogue shape for a business read just means "no date/status filters".
            args = self.arguments = BusinessLookupArguments(query=args.query, store_id=args.store_id, limit=args.limit,
                                                            from_date=None, to_date=None, as_of=None, status=None)
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
