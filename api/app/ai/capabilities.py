"""Explicit read adapters; database configuration can restrict but cannot add code."""
import hashlib
import json
from dataclasses import dataclass

from fastapi import HTTPException

from app.ai.schemas import (
    BusinessLookupArguments, CATALOGUE_KEYS, COMPANY_LEDGER_KEYS, STORE_READ_KEYS,
    CapabilityKey, LookupArguments, ReadLookup, CapabilityUpdate, TenantCapabilityUpdate,
)
from app.ai.business_reads import business_lookup
from app.services.access import allowed_stores, check_module
from app.services.feature_controls import audit_platform, lock_policy
from app.services.inventory_service import InventoryService
from app.services.masters_service import MastersService
from app.services.parties_service import PartiesService
from app.services.stores_service import StoresService
from sqlalchemy import text


@dataclass(frozen=True)
class ReadCapability:
    key: CapabilityKey
    module_path: str
    description: str
    fields: tuple[str, ...]
    adapter_version: int = 1

    @property
    def fingerprint(self) -> str:
        contract = {"key": self.key, "path": self.module_path, "safety": "read",
                    "adapter_version": self.adapter_version, "fields": self.fields,
                    "input": (LookupArguments if self.key in CATALOGUE_KEYS else BusinessLookupArguments).model_json_schema()}
        return hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()


REGISTRY = {
    entry.key: entry for entry in (
        ReadCapability("stores", "/stores", "Find active permitted stores by name/code.",
                       ("id", "name", "code", "kind", "holds_stock")),
        ReadCapability("products", "/inventory", "Find active products by name/SKU and stock across permitted stores. Optional store_id must come from a store lookup. Includes draft flag and all variants combined, not variant-specific stock or prices.",
                       ("id", "name", "sku", "hsn_code", "is_draft", "stock_qty")),
        ReadCapability("parties", "/parties", "Find active customers/vendors by name. Returns type/name/GST only, no contact details.",
                       ("id", "legal_name", "nickname", "party_type", "gst_number")),
        ReadCapability("hsn", "/masters", "Find configured active HSN/SAC codes and GST rates by code or description. Do not infer a classification from a product name.",
                       ("id", "code", "description", "gst_rate")),
        ReadCapability("brands", "/inventory", "Find brand names and codes.",
                       ("id", "name", "code", "is_active")),
        ReadCapability("categories", "/inventory", "Find product category names and codes.",
                       ("id", "name", "code", "is_active")),
        ReadCapability("accounts", "/accounts", "Search active account names and balances as_of a date (null=today). Company-wide ledger requires unrestricted store access. No bank/contact details. Empty query lists a bounded subset.",
                       ("account_id", "account_name", "account_type", "is_company_account", "opening_balance",
                        "total_inflow", "total_outflow", "current_balance", "transaction_count", "last_transaction_date")),
        ReadCapability("transactions", "/accounts", "Search posted transactions by account nickname/reference/category and transaction date range. Includes reversals; requires unrestricted store access. No descriptions or account credentials.",
                       ("id", "from_account_name", "to_account_name", "direction", "amount", "payment_mode",
                        "category", "transaction_date", "source_type", "is_reversed", "reversal_of_transaction_id")),
        ReadCapability("invoices", "/billing", "Search invoices by number/customer, invoice date range and current collection status UNPAID/PARTIAL/SETTLED/BAD_DEBT, or CANCELLED document status. Optional verified store_id. Empty query returns recent bounded records, not totals.",
                       ("id", "invoice_number", "customer_name", "store_code", "invoice_date", "total",
                        "amount_received", "status", "collection_status", "due_date")),
        ReadCapability("purchases", "/purchases", "Search purchase bills by bill/voucher/vendor, purchase date range, current payment status UNPAID/PARTIAL/PAID or CANCELLED document status. Optional verified store_id. Includes receipt state, no line items.",
                       ("id", "voucher_number", "bill_number", "vendor_name", "store_code", "purchase_date",
                        "total", "amount_paid", "balance_amount", "payment_status", "receipt_status", "status", "due_date")),
        ReadCapability("receivables", "/collections", "Search current receivables by party/reference, due-date range and UNPAID/PARTIAL/SETTLED/BAD_DEBT. Optional verified store_id. Store-limited users cannot see standalone receivables without an invoice store.",
                       ("id", "party_name", "amount_due", "amount_received", "balance_amount", "status", "due_date")),
        ReadCapability("refunds", "/settlements", "Search refunds by document/party, creation-date range and PENDING/SETTLED. Optional verified store_id. PAY_CUSTOMER versus RECEIVE_VENDOR denotes refund direction. No global totals.",
                       ("id", "direction", "document_type", "document_number", "party_name", "amount",
                        "status", "settled_on", "payment_mode", "created_at")),
        ReadCapability("borrowings", "/settlements", "Search current borrowing balances by party name. Excludes reversals, requires unrestricted stores. Positive outstanding means money owed to party. No historical or date/status/store filters.",
                       ("party_id", "party_name", "borrowed_amount", "repaid_amount", "net_outstanding")),
        ReadCapability("reorder", "/inventory", "Search reorder reminders by product name/SKU; optional verified store_id. Empty query lists bounded reminders. Quantities include only permitted stores compared with configured thresholds, not company totals.",
                       ("product_id", "variant_id", "product_name", "variant_name", "stock_qty", "reorder_level",
                        "reorder_quantity", "reminder_date", "reminder_due", "low_stock")),
        ReadCapability("reconciliation", "/inventory", "Search per-store stock reconciliation by product name/SKU; optional verified store_id. Balance minus movements and missing document count. Empty query lists bounded records including zero differences; no date/status filters.",
                       ("store_code", "product_name", "variant_name", "balance_quantity", "movement_quantity",
                        "difference", "movement_count", "missing_document_references")),
        ReadCapability("period_locks", "/accounts", "Search currently active accounting locks by reason or overlapping date range. as_of checks a date against currently active locks, NOT historical state. Empty query lists bounded locks. No matches do not guarantee posting is allowed.",
                       ("id", "period_start", "period_end", "is_active")),
    )
}


def platform_capabilities(db, company_id=None):
    if company_id is not None and not db.execute(
        text("select id from companies where id=:id"), {"id": str(company_id)}
    ).first():
        raise HTTPException(404, "Workspace not found")
    rows = db.execute(text("""select c.*,coalesce(t.allowed,false) as tenant_allowed,
        coalesce(t.version,0) as tenant_version from ai_capabilities c
        left join ai_tenant_capabilities t on t.capability_key=c.key and t.company_id=cast(:company as uuid)
        order by c.key"""), {"company": str(company_id) if company_id else None}).mappings()
    items = []
    for row in rows:
        adapter = REGISTRY.get(row["key"])
        compatible = bool(adapter and row["schema_fingerprint"] == adapter.fingerprint)
        items.append({**dict(row), "description": adapter.description if adapter else "Adapter not deployed",
                      "module_path": adapter.module_path if adapter else None, "safety": "read",
                      "compatible": compatible, "reason": None if compatible else "Contract requires platform review"})
    return {"items": items}


def save_capability(db, key: CapabilityKey, payload: CapabilityUpdate, admin_id):
    lock_policy(db)
    row = db.execute(text("select * from ai_capabilities where key=:key"), {"key": key}).mappings().first()
    if not row:
        raise HTTPException(404, "Capability not found")
    if row["version"] != payload.expected_version:
        raise HTTPException(409, "Capability changed. Refresh before saving.")
    fingerprint = REGISTRY[key].fingerprint if payload.approve_contract else row["schema_fingerprint"]
    if payload.enabled and fingerprint != REGISTRY[key].fingerprint:
        raise HTTPException(409, "Review and approve the current read contract before enabling.")
    db.execute(text("""update ai_capabilities set enabled=:enabled,schema_fingerprint=:fingerprint,
        version=version+1,updated_at=now(),updated_by=:admin where key=:key"""),
        {"key": key, "enabled": payload.enabled, "fingerprint": fingerprint, "admin": admin_id})
    audit_platform(db, admin_id, f"AI_CAPABILITY_{key.upper()}_UPDATED")
    db.commit()
    return platform_capabilities(db)


def save_tenant_capability(db, company_id, key: CapabilityKey, payload: TenantCapabilityUpdate, admin_id):
    lock_policy(db)
    if not db.execute(text("select id from companies where id=:id"), {"id": str(company_id)}).first():
        raise HTTPException(404, "Workspace not found")
    row = db.execute(text("""select version from ai_tenant_capabilities
        where company_id=:company and capability_key=:key"""), {"company": str(company_id), "key": key}).first()
    if (row[0] if row else 0) != payload.expected_version:
        raise HTTPException(409, "Tenant capability changed. Refresh before saving.")
    db.execute(text("""insert into ai_tenant_capabilities(company_id,capability_key,allowed,updated_by)
        values(:company,:key,:allowed,:admin) on conflict(company_id,capability_key) do update
        set allowed=excluded.allowed,version=ai_tenant_capabilities.version+1,updated_at=now(),updated_by=excluded.updated_by"""),
        {"company": str(company_id), "key": key, "allowed": payload.allowed, "admin": admin_id})
    audit_platform(db, admin_id, f"AI_TENANT_CAPABILITY_{key.upper()}_UPDATED", str(company_id))
    db.commit()
    return platform_capabilities(db, company_id)


def current_identity(db, identity):
    row = db.execute(text("select * from tenali_ai_member_scope()")).mappings().first()
    if not row:
        raise HTTPException(403, "AI member access changed. Sign in again.")
    refreshed = {**identity, **dict(row)}
    db.info["tenant_context"] = refreshed
    return refreshed


def available_capabilities(db, identity):
    items = platform_capabilities(db, identity["company_id"])["items"]
    available = []
    for item in items:
        if not item["enabled"] or not item["compatible"] or not item["tenant_allowed"]:
            continue
        if item["key"] in COMPANY_LEDGER_KEYS and allowed_stores(identity) is not None:
            continue
        try:
            check_module(identity, REGISTRY[item["key"]].module_path)
        except HTTPException as error:
            if error.status_code != 403:
                raise
            continue
        available.append({"key": item["key"], "description": item["description"], "version": item["version"],
                          "tenant_version": item["tenant_version"]})
    return available


def execute_lookup(db, identity, lookup: ReadLookup):
    key, args = lookup.capability, lookup.arguments
    check_module(identity, REGISTRY[key].module_path)
    if args.store_id is not None and key not in STORE_READ_KEYS:
        raise HTTPException(422, "This lookup does not accept a store filter.")
    company = str(identity["company_id"])
    # One extra row detects incomplete results without loading a full catalogue.
    limit = args.limit + 1
    if isinstance(args, BusinessLookupArguments):
        result = business_lookup(db, identity, key, args)
    elif key == "products":
        result = InventoryService(db, company).search_stock(args.query, limit, str(args.store_id) if args.store_id else None)
    elif key == "stores":
        result = StoresService(db, company).list_stores(False, search=args.query, limit=limit)
    elif key == "parties":
        result = PartiesService(db).list(company, search=args.query, limit=limit)
    elif key == "hsn":
        result = MastersService(db).list_hsn(company, search=args.query, limit=limit)
    else:
        result = InventoryService(db, company).master_entries(key, search=args.query, limit=limit)
    fields = REGISTRY[key].fields
    rows = [{field: row.get(field) for field in fields} for row in result["items"][:args.limit]]
    return {"capability": key, "items": rows, "more_matches": len(result["items"]) > args.limit,
            "note": result.get("note", result.get("stock_scope", "Partial name/code matches; clarify ambiguous matches. No company-wide totals."))}


def format_lookup(result, budget: int) -> str:
    rows = result["items"]
    # Database labels may be long or contain instructions. Render as data, never executable content.
    rendered = json.dumps(result, default=str, ensure_ascii=False)
    while len(rendered) > budget and rows:
        rows.pop()
        result["more_matches"] = True
        result["note"] += " Output limited; narrow your query."
        rendered = json.dumps(result, default=str, ensure_ascii=False)
    if len(rendered) > budget:
        raise HTTPException(422, "Lookup output is too large. Narrow your query.")
    return "\n\nVerified Tenali lookup (read only):\n" + rendered
