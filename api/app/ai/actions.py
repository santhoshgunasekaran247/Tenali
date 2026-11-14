"""Reviewed operational draft contracts. Approval is not business execution."""
import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import ReadAssistantOutput
from app.schemas.accounts import AccountCreate, AccountUpdate, AccountTransactionCreate, BusinessPaymentCreate, TransactionReverseCreate
from app.schemas.billing import InvoiceCreate
from app.schemas.collections import ReceivablePaymentCreate
from app.schemas.inventory import (ProductInput, StockAdjustment, StockTransferCreate, VariantInput,
    VendorOfferInput, BulkVendorMapping, ProductMerge, StockTransferReverse, ExternalMovementSource,
    ReorderReminder, InventoryLookupCreate)
from app.schemas.parties import PartyCreate, PartyUpdate
from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate, PurchaseReceiptConfirm
from app.schemas.money import PositiveMoney, SignedMoney
from app.services.document_cancellation import Cancellation
from datetime import date
from decimal import Decimal


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


class AccountCreateDraft(AccountCreate):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    opening_balance: SignedMoney
    is_company_account: bool
    holder_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)


class AccountUpdateDraft(AccountUpdate):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    holder_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)


class TransactionCreateDraft(AccountTransactionCreate):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    transaction_date: date
    payment_mode: str = Field(min_length=1, max_length=50)
    reference: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    description: str = Field(min_length=1, max_length=1000)


class BusinessPaymentDraft(BusinessPaymentCreate):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    purpose: Literal["purchase", "billing", "expense"]
    transaction_date: date
    payment_mode: str = Field(min_length=1, max_length=50)
    reference: str | None = Field(default=None, max_length=200)
    notes: str = Field(min_length=1, max_length=1000)
    create_borrowing: bool


class TransactionReverseDraft(TransactionReverseCreate):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    transaction_date: date
    notes: str = Field(min_length=1, max_length=1000)


class BorrowingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    party_id: UUID
    direction: Literal["borrow", "repay", "lend", "collect"]
    amount: PositiveMoney
    transaction_date: date
    account_id: UUID | None = None
    reference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)
    create_account_transaction: bool


class RefundDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    account_id: UUID
    settled_on: date
    payment_mode: str = Field(min_length=1, max_length=50)
    reference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


class ReceivableDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    party_id: UUID
    invoice_id: UUID | None = None
    reference: str | None = Field(default=None, max_length=200)
    amount_due: PositiveMoney
    due_date: date
    reminder_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)


class ReceivableStatusDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["UNPAID", "PARTIAL", "SETTLED", "BAD_DEBT"]
    bad_debt_reason: str | None = Field(default=None, max_length=1000)
    reminder_date: date | None = None


class ReceivableReminderDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    next_reminder_date: date | None
    notes: str = Field(min_length=1, max_length=1000)


class VariantCreateDraft(VariantInput):
    product_id: UUID


class VariantUpdateDraft(VariantInput):
    product_id: UUID


class OfferDraft(VendorOfferInput):
    product_id: UUID


class EmptyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["account_transactions", "account_journal", "sales_register", "purchase_register", "ar_aging", "ap_aging"]
    from_date: date | None = None
    to_date: date | None = None
    as_of: date | None = None
    period: Literal["daily", "weekly", "monthly", "yearly"] = "daily"


class GSTReconcileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(min_length=1, max_length=12000)
    from_date: date
    to_date: date


class PurchaseBundleDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    vendor_name: str = Field(default="", max_length=300)
    create_vendor_if_missing: bool = True
    vendor_party_id: UUID | None = None
    product_name: str = Field(default="", max_length=200)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    rate: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    hsn: str | None = Field(default=None, pattern=r"^\d{4,8}$")
    gst_rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    price_includes_gst: bool | None = None
    selling_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    store_name: str = Field(default="", max_length=120)
    store_id: UUID | None = None
    purchase_date: date | None = None
    payment_mode: str = Field(default="", max_length=50)
    account_name: str = Field(default="", max_length=200)
    account_id: UUID | None = None
    fully_paid: bool | None = None
    received_now: bool | None = None

ActionKey = Literal[
    "expense_create", "purchase_create", "purchase_bundle_create", "invoice_create", "party_create", "party_update",
    "product_create", "product_update", "stock_adjust", "stock_transfer",
    "purchase_payment", "collection_payment",
    "invoice_cancel", "purchase_cancel", "product_delete", "transaction_delete",
    "account_create", "account_update", "account_transaction_create", "account_transaction_reverse",
    "borrowing_create", "refund_settle", "receivable_create", "receivable_status", "receivable_reminder",
    "purchase_receive", "product_confirm", "product_merge", "variant_create", "variant_update",
    "offer_create", "offer_update", "vendor_bulk_map", "brand_create", "brand_update",
    "category_create", "category_update", "reorder_reminder", "stock_transfer_reverse", "movement_attribute",
    "report_export", "gst_reconcile",
    "business_payment_create",
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
        return self.key in {"invoice_cancel", "purchase_cancel", "product_delete", "transaction_delete",
                            "account_transaction_reverse", "product_merge", "stock_transfer_reverse", "receivable_status"}

    @property
    def company_wide(self):
        return self.key in {"account_create", "account_update", "account_transaction_create",
                            "account_transaction_reverse", "borrowing_create", "product_merge", "vendor_bulk_map",
                            "report_export", "gst_reconcile", "business_payment_create"}

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
        Action("purchase_bundle_create", "/purchases", PurchaseBundleDraft, None,
            "Prepare one reviewed chain for vendor (reuse an exact match or create if absent), new product, purchase, full payment and stock receipt. Resolve names in the server. HSN/SAC must be an active company master. No separate stock adjustment."),
    Action("invoice_create", "/billing", InvoiceCreate, None,
           "Customer and inventory → sales invoice → stock OUT and linked Collections receivable. Received payment also creates the account inflow in the same posting; never add a duplicate stock adjustment or account transaction."),
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
    Action("account_create", "/accounts", AccountCreateDraft, None, "Create an account with explicit opening balance and company-account choice."),
    Action("account_update", "/accounts", AccountUpdateDraft, "accounts", "Patch supplied account fields only; opening balances cannot change after transactions."),
    Action("account_transaction_create", "/accounts", TransactionCreateDraft, None, "Post one manual inflow/outflow/transfer. Do not duplicate invoice, purchase or borrowing payments."),
    Action("account_transaction_reverse", "/accounts", TransactionReverseDraft, "account_transactions", "Reverse one transaction through the existing linked-ledger workflow; never reverse a reversal."),
    Action("borrowing_create", "/settlements", BorrowingDraft, None, "Party loan entry with explicit account-transaction choice; repay/collect cannot exceed outstanding."),
    Action("refund_settle", "/settlements/refunds", RefundDraft, "refund_settlements", "Settle an existing pending cancellation refund in Accounts; no duplicate money entry."),
    Action("receivable_create", "/collections", ReceivableDraft, None, "Create a receivable with due date; invoice-linked amount/customer must match the invoice."),
    Action("receivable_status", "/collections", ReceivableStatusDraft, "receivables", "Separate high-impact ledger-derived status or bad-debt change; requires bad-debt reason. No fabricated settlement."),
    Action("receivable_reminder", "/collections", ReceivableReminderDraft, "receivables", "Record a reminder and next date in existing history. Does not send messages to the customer."),
    Action("purchase_receive", "/purchases", PurchaseReceiptConfirm, "purchases", "Confirm receipt of an existing purchase once; inventory is booked by the purchase workflow."),
    Action("product_confirm", "/inventory", EmptyDraft, "products", "Confirm a purchase-created draft product after HSN validation."),
    Action("product_merge", "/inventory", ProductMerge, "products", "Separate owner/admin-only draft merge into an active product/variant; moves history/stock/offers and removes the draft."),
    Action("variant_create", "/inventory", VariantCreateDraft, None, "Create a variant of a resolved product. Does not add stock."),
    Action("variant_update", "/inventory", VariantUpdateDraft, "product_variants", "Full replacement of one variant; preserve every existing field."),
    Action("offer_create", "/inventory", OfferDraft, None, "Map a vendor offer to a product/variant; vendor availability is not owned stock."),
    Action("offer_update", "/inventory", OfferDraft, "vendor_contributions", "Replace offer fields; product/variant/vendor identity cannot change."),
    Action("vendor_bulk_map", "/inventory", BulkVendorMapping, None, "Map one vendor to explicitly resolved products without stock changes; existing mappings remain untouched."),
    Action("brand_create", "/inventory", InventoryLookupCreate, None, "Create an inventory brand."),
    Action("brand_update", "/inventory", InventoryLookupCreate, "brands", "Replace the name/description/active fields of an inventory brand."),
    Action("category_create", "/inventory", InventoryLookupCreate, None, "Create an inventory category."),
    Action("category_update", "/inventory", InventoryLookupCreate, "product_categories", "Replace the name/description/active fields of an inventory category."),
    Action("reorder_reminder", "/inventory", ReorderReminder, "products", "Set a product/variant reorder reminder; no automatic order."),
    Action("stock_transfer_reverse", "/inventory", StockTransferReverse, "stock_transfers", "Separate high-impact reversal back to the original store, dated today; requires available destination stock."),
    Action("movement_attribute", "/inventory", ExternalMovementSource, "stock_movements", "Re-attribute only movements whose invoice/purchase source is missing; never change quantity or balances."),
    Action("report_export", "/reports", ReportDraft, None, "Prepare one private CSV download of transactions/journal/sales/purchases/AR/AP. Explicit date range or aging as_of required. No export content goes into chat or the immutable outcome."),
    Action("gst_reconcile", "/reports", GSTReconcileDraft, None, "Reconcile normalized GSTR-2B CSV (up to 12000 characters) against purchases for explicit dates; private CSV working paper only, no filing or ITC determination."),
    Action("business_payment_create", "/accounts", BusinessPaymentDraft, None, "Post a standalone business OUTFLOW with explicit purchase/billing/expense purpose and borrowing choice. Does NOT settle purchase bills or invoices; use purchase_payment/collection_payment for those."),
)}


class DraftProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: ActionKey = Field(description="The user's end operation, NOT a missing prerequisite. A sale to a new customer is invoice_create, not party_create.")
    target_id: UUID | Annotated[str, Field(min_length=2, max_length=200)] | None
    payload_json: str = Field(max_length=10000, description="All known facts for the root operation, including earlier user messages. Incomplete payloads are valid; omit unknowns. Put record names in reference ID fields.")
    workflow_id: UUID | None = None


class ActionAssistantOutput(ReadAssistantOutput):
    draft: DraftProposal | None = Field(description="Required for any supported operational request, even with missing information. Null only for informational or unsupported requests. Prerequisite creation is handled by the server.")


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
