"""Reviewed operational draft contracts. Approval is not business execution."""
import hashlib
import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import ReadAssistantOutput
from app.schemas.accounts import BusinessPaymentCreate
from app.schemas.billing import InvoiceCreate
from app.schemas.collections import ReceivablePaymentCreate
from app.schemas.inventory import ProductInput, StockAdjustment, StockTransferCreate
from app.schemas.parties import PartyCreate, PartyUpdate
from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate
from app.schemas.money import PositiveMoney
from app.services.document_cancellation import Cancellation
from datetime import date


class CancellationDraft(Cancellation):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cancellation_date: date


class DeleteDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=1000)


class TransactionDeleteDraft(DeleteDraft):
    kind: Literal["purchase", "purchase_payment", "receivable_payment", "account_transaction",
                  "stock_adjustment", "stock_transfer", "borrowing", "cod_settlement"]
    record_id: UUID
    cascade: bool = False


class CollectionDraft(ReceivablePaymentCreate):
    amount: PositiveMoney


class PartyCreateDraft(PartyCreate):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    legal_name: str = Field(min_length=1, max_length=300)


class PartyUpdateDraft(PartyUpdate):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    legal_name: str | None = Field(default=None, min_length=1, max_length=300)

ActionKey = Literal[
    "expense_create", "purchase_create", "invoice_create", "party_create", "party_update",
    "product_create", "product_update", "stock_adjust", "stock_transfer",
    "purchase_payment", "collection_payment",
    "invoice_cancel", "purchase_cancel", "product_delete", "transaction_delete",
]


@dataclass(frozen=True)
class Action:
    key: ActionKey
    path: str
    schema: type[BaseModel]
    target: str | None
    description: str
    version: int = 2

    @property
    def high_impact(self):
        return self.key in {"invoice_cancel", "purchase_cancel", "product_delete", "transaction_delete"}

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps({
            "key": self.key, "path": self.path, "schema": self.schema.model_json_schema(),
            "target": self.target, "version": self.version, "safety": "approved_atomic_execution",
        }, sort_keys=True).encode()).hexdigest()


ACTIONS = {action.key: action for action in (
    Action("expense_create", "/accounts", BusinessPaymentCreate, None,
           "Draft an expense payment, not a purchase payment. Requires amount, source account, mode, date and explicit borrowing choice."),
    Action("purchase_create", "/purchases", PurchaseCreate, None,
           "Draft a purchase bill with lines/store/vendor/payment/received_now. Existing service computes taxes and inventory later; never separately duplicate stock."),
    Action("invoice_create", "/billing", InvoiceCreate, None,
           "Draft a sales invoice with resolved customer/store/lines/payment. No invoice update or cancellation."),
    Action("party_create", "/parties", PartyCreateDraft, None, "Draft a vendor/customer record, clarify possible duplicates."),
    Action("party_update", "/parties", PartyUpdateDraft, "parties", "Draft a patch to a resolved vendor/customer. Only supplied fields change."),
    Action("product_create", "/inventory", ProductInput, None, "Draft a product. No stock is added by product creation."),
    Action("product_update", "/inventory", ProductInput, "products",
           "Draft a full product replacement, not a patch. Preserve all existing fields; ask the user to review omitted/defaulted fields."),
    Action("stock_adjust", "/inventory", StockAdjustment, "products", "Draft an explicit IN/OUT stock adjustment with store, quantity and reason."),
    Action("stock_transfer", "/inventory", StockTransferCreate, None, "Draft a stock transfer between two permitted stores."),
    Action("purchase_payment", "/purchases", PurchasePaymentCreate, "purchases", "Draft payment against an existing resolved purchase, not a new expense."),
    Action("collection_payment", "/collections", CollectionDraft, "receivables", "Draft collection against an existing resolved receivable."),
    Action("invoice_cancel", "/billing", CancellationDraft, "invoices",
           "Separate high-impact invoice cancellation. Review payment reversals, pending refunds and stock return. Never delete a tax invoice."),
    Action("purchase_cancel", "/purchases", CancellationDraft, "purchases",
           "Separate high-impact purchase cancellation. Review reversed payments, pending vendor refunds and removal of received stock."),
    Action("product_delete", "/inventory", DeleteDraft, "products",
           "Separate high-impact deletion of an unused product only. Products with stock/history must instead be made inactive."),
    Action("transaction_delete", "/accounts", TransactionDeleteDraft, None,
           "Separate high-impact deletion of one resolved transaction with existing dependency analysis. No reset-all, invoice deletion, administrative changes or online-order deletion."),
)}


class DraftProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: ActionKey
    target_id: UUID | None
    payload_json: str = Field(max_length=10000)


class ActionAssistantOutput(ReadAssistantOutput):
    draft: DraftProposal | None


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: ActionKey
    target_id: UUID | None = None
    payload: dict = Field(default_factory=dict)
    client_key: UUID


class DraftEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict
    expected_version: int = Field(ge=1)


class DraftApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    expected_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ExecutionApproval(DraftApproval):
    confirm_text: str | None = Field(default=None, max_length=300)


class ActionPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    approve_contract: bool = False
    expected_version: int = Field(ge=1)
    execution_enabled: bool = False


class TenantActionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed: bool
    expected_version: int = Field(ge=0)
