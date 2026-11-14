"""Explicit read adapters; database configuration can restrict but cannot add code."""
import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException

from app.ai.schemas import (
    BusinessLookupArguments, CATALOGUE_KEYS, COMPANY_LEDGER_KEYS, STORE_READ_KEYS,
    CapabilityKey, LookupArguments, ReadLookup, CapabilityUpdate, TenantCapabilityUpdate,
    DATED_READ_KEYS, AS_OF_READ_KEYS, READ_STATUSES, business_today,
)
from app.ai.business_reads import business_lookup
from app.services.access import allowed_stores, check_module
from app.services.feature_controls import audit_platform, lock_policy
from app.services.inventory_service import InventoryService
from app.services.masters_service import MastersService
from app.services.parties_service import PartiesService
from app.services.stores_service import StoresService
from app.schemas.inventory import ProductInput, VariantInput, VendorOfferInput
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
        ReadCapability("borrowings", "/settlements", "Search current loan balances by party name. Excludes reversals, requires unrestricted stores. net_outstanding=we owe party; net_receivable=party owes us. No date/status/store filters.",
                       ("party_id", "party_name", "borrowed_amount", "repaid_amount", "net_outstanding",
                        "lent_amount", "collected_amount", "net_receivable")),
        ReadCapability("reorder", "/inventory", "Search reorder reminders by product name/SKU; optional verified store_id. Empty query lists bounded reminders. Quantities include only permitted stores compared with configured thresholds, not company totals.",
                       ("product_id", "variant_id", "product_name", "variant_name", "stock_qty", "reorder_level",
                        "reorder_quantity", "reminder_date", "reminder_due", "low_stock")),
        ReadCapability("reconciliation", "/inventory", "Search per-store stock reconciliation by product name/SKU; optional verified store_id. Balance minus movements and missing document count. Empty query lists bounded records including zero differences; no date/status filters.",
                       ("store_code", "product_name", "variant_name", "balance_quantity", "movement_quantity",
                        "difference", "movement_count", "missing_document_references")),
        ReadCapability("period_locks", "/accounts", "Search currently active accounting locks by reason or overlapping date range. as_of checks a date against currently active locks, NOT historical state. Empty query lists bounded locks. No matches do not guarantee posting is allowed.",
                       ("id", "period_start", "period_end", "is_active")),
        ReadCapability("product_details", "/inventory", "Product fields for full replacement; query by name/SKU or exact verified UUID. No stock totals.",
                       ("id", "is_draft", *ProductInput.model_fields)),
        ReadCapability("variants", "/inventory", "Variant fields for creation/update; query by product/variant name, SKU or verified UUID. No stock totals.",
                       ("id", "product_id", "product_name", *VariantInput.model_fields)),
        ReadCapability("vendor_offers", "/inventory", "Vendor offer fields/IDs; query by product/vendor name or verified UUID. Availability is not owned stock.",
                       ("id", "product_id", "product_name", *VendorOfferInput.model_fields)),
        ReadCapability("borrowing_entries", "/settlements", "Individual active borrowing/repayment entries by party/verified UUID and transaction date range. Unrestricted stores only.",
                       ("id", "party_id", "party_name", "direction", "amount", "transaction_date", "account_id", "source_transaction_id")),
        ReadCapability("stock_transfers", "/inventory", "Transfers by store/reference/verified UUID and date range, only where both stores are permitted. Optional store filter.",
                       ("id", "from_store_id", "to_store_id", "from_store_code", "to_store_code", "transfer_date", "reference", "reversal_of_transfer_id", "reversed_by_transfer_id")),
        ReadCapability("stock_movements", "/inventory", "Per-store movements by product/variant label or verified UUID and creation-date range. Optional permitted store filter.",
                       ("id", "store_id", "store_code", "product_id", "product_name", "variant_id", "variant_name", "movement_type", "quantity", "reference_type", "reference_id", "created_at")),
        ReadCapability("movement_sources", "/inventory", "Movements with missing invoice/purchase sources, by product/verified UUID, creation dates and permitted store.",
                       ("id", "store_id", "store_code", "product_id", "product_name", "variant_id", "movement_type", "quantity", "reference_type", "reference_id")),
        ReadCapability("collection_reminders", "/collections", "Due reminders by party/receivable UUID, as_of (null=today) and permitted store.",
                       ("id", "party_id", "party_name", "invoice_id", "status", "amount_due", "amount_received", "due_date", "reminder_date")),
        ReadCapability("reminder_history", "/collections", "Recorded reminders by party/receivable UUID, reminded-at date range and permitted store. No notes or actors.",
                       ("id", "receivable_id", "party_name", "reminder_date", "next_reminder_date", "reminded_at")),
        ReadCapability("account_journal", "/accounts", "Bounded daily journal entries with explicit optional dates, no text search or totals; use report_export for complete CSV. Unrestricted stores.",
                       ("id", "period_key", "direction", "amount", "from_account_name", "to_account_name", "category", "transaction_date", "is_reversed")),
        ReadCapability("audit_events", "/reports", "Audit identifiers/actions by action/entity text and creation date range. No actors or private old/new payloads. Unrestricted stores.",
                       ("id", "action", "entity_type", "entity_id", "created_at")),
        ReadCapability("business_payments", "/accounts", "Original standalone outflows by account/reference/category and transaction dates; is_reversed marks reversed originals. Reversal entries are in transactions. Not bill settlement. Unrestricted stores.",
                       ("id", "from_account_name", "to_account_name", "direction", "amount", "payment_mode", "category",
                        "transaction_date", "source_type", "is_reversed", "reversal_of_transaction_id")),
    )
}

READ_CONTEXT_NOTES = {
    "stores": "active name/code",
    "products": "name/SKU;stock sums variants,permitted stores",
    "parties": "customer/vendor name;empty=list;no contacts",
    "hsn": "active code/description;never infer tax",
    "brands": "name/code",
    "categories": "name/code",
    "accounts": "names;empty=all with balances at as_of",
    "transactions": "nickname/reference/category;dates;includes reversals",
    "invoices": "number/customer;invoice dates",
    "purchases": "bill/voucher/vendor;purchase dates",
    "receivables": "party/reference;due dates;current balances",
    "refunds": "document/party;dates;PAY_CUSTOMER owed,RECEIVE_VENDOR due back",
    "borrowings": "party;we owe=net_outstanding;owes us=net_receivable",
    "reorder": "product/SKU;stock vs thresholds",
    "reconciliation": "empty=current stock per store/product;product/SKU",
    "period_locks": "reason;overlapping dates;as_of tests CURRENT active locks",
    "product_details": "product name/SKU/verified UUID;replacement fields;no stock totals",
    "variants": "product/variant name/SKU/UUID;replacement fields;no stock totals",
    "vendor_offers": "product/vendor name/UUID;offer fields;not owned stock",
    "borrowing_entries": "party/entry UUID;transaction dates;active entries exclude reversals",
    "stock_transfers": "store/reference/UUID;transfer dates;both stores must be permitted",
    "stock_movements": "product/variant/UUID;creation dates;permitted-store movements",
    "movement_sources": "product/UUID;creation dates;missing invoice/purchase sources",
    "collection_reminders": "party/receivable UUID;reminders due by as_of",
    "reminder_history": "party/receivable UUID;reminded-at dates;no notes/actors",
    "account_journal": "EMPTY query only;daily entries;date window default=today;no totals",
    "audit_events": "action/entity text;creation dates;no actors or private payloads",
    "business_payments": "original outflows;account/reference/category;dates;not settlement",
}


def read_context(key):
    filters = ["q"]
    if key in STORE_READ_KEYS:
        filters.append("s")
    if key in DATED_READ_KEYS:
        filters.append("d")
    if key in AS_OF_READ_KEYS:
        filters.append("a")
    if key in READ_STATUSES:
        filters.append("status=" + "/".join(sorted(READ_STATUSES[key])))
    return READ_CONTEXT_NOTES[key] + ";" + ",".join(filters)


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


LISTABLE_READS = {"accounts", "stores", "parties", "brands", "categories", "hsn"}
TITLE_FIELDS = ("name", "legal_name", "product_name", "account_name", "invoice_number", "voucher_number", "bill_number",
                "party_name", "customer_name", "vendor_name", "code", "store_code", "nickname", "reference")


def row_title(row):
    return next((str(row[key]) for key in TITLE_FIELDS if row.get(key) not in (None, "")), "")


def with_arguments(lookup, **values):
    return lookup.model_copy(update={"arguments": lookup.arguments.model_copy(update=values)})


def singular(word):
    return word[:-1] if word.endswith("s") and not word.endswith("ss") and len(word) > 4 else word


def relaxed_queries(query):
    words = re.findall(r"\w+", query.lower())
    base = [singular(word) for word in words]
    exact = [" ".join(base)] if base != words else []
    if len(base) > 1:
        exact.append(max(base, key=len))
    prefixes = list(dict.fromkeys(word[:3] for word in base if len(word) >= 4))[:3]
    return [value for value in dict.fromkeys(exact) if len(value) >= 2 and value != query.lower()], prefixes


def period_range(words, today):
    """Relative periods people say ("today", "last week") become an explicit inclusive date range."""
    joined = " ".join(words)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    previous_month_end = month_start - timedelta(days=1)
    periods = (
        ("last week", (week_start - timedelta(days=7), week_start - timedelta(days=1))),
        ("this week", (week_start, today)),
        ("last month", (previous_month_end.replace(day=1), previous_month_end)),
        ("this month", (month_start, today)),
        ("this year", (today.replace(month=1, day=1), today)),
        ("yesterday", (today - timedelta(days=1), today - timedelta(days=1))),
        ("today", (today, today)), ("todays", (today, today)),
    )
    for phrase, dates in periods:
        if re.search(rf"\b{phrase}\b", joined):
            return phrase, dates
    return None, None


STATUS_WORDS = {"unpaid": "UNPAID", "pending": "UNPAID", "due": "UNPAID", "outstanding": "UNPAID", "partial": "PARTIAL",
                "partly": "PARTIAL", "paid": "PAID", "settled": "SETTLED", "cancelled": "CANCELLED", "canceled": "CANCELLED"}
PARTY_WORDS = {"vendor": "vendor", "supplier": "vendor", "customer": "customer", "client": "customer", "buyer": "customer"}
GENERIC_WORDS = {
    "a", "all", "an", "any", "are", "below", "bill", "by", "current", "do", "for", "from", "have", "how", "i", "in", "invoice",
    "inventory", "is", "item", "level", "list", "low", "many", "me", "much", "my", "now", "of", "on", "please", "pls",
    "product", "purchase", "recent", "reorder", "sale", "sales", "show", "stock", "the", "total", "what", "which", "with",
    "week", "month", "year", "last", "this", "today", "todays", "yesterday", "balance", "account", "party", "parties",
}


def interpret_lookup(lookup: ReadLookup, today):
    """Turns descriptive words in a search into typed filters; returns (lookup, party_type, notes)."""
    words = [singular(word)
             for word in re.findall(r"\w+", lookup.arguments.query.lower())]
    args, updates, notes, party_type = lookup.arguments, {}, [], None
    if isinstance(args, BusinessLookupArguments):
        phrase, dates = period_range(words, today)
        if dates and lookup.capability in DATED_READ_KEYS and not (args.from_date or args.to_date):
            updates.update(from_date=dates[0], to_date=dates[1])
            notes.append(f"{phrase.capitalize()} = {dates[0]} to {dates[1]}.")
        allowed = READ_STATUSES.get(lookup.capability, set())
        if args.status is None:
            for word in words:
                status = STATUS_WORDS.get(word)
                status = "PENDING" if status == "UNPAID" and "PENDING" in allowed else status
                status = "SETTLED" if status == "PAID" and "SETTLED" in allowed else status
                if status in allowed:
                    updates["status"] = status
                    notes.append(f"Status {status.replace('_', ' ').lower()}.")
                    break
    if lookup.capability == "parties":
        party_type = next((PARTY_WORDS[word] for word in words if word in PARTY_WORDS), None)
    remaining = [word for word in words if word not in GENERIC_WORDS and word not in STATUS_WORDS and word not in PARTY_WORDS]
    updates["query"] = " ".join(remaining) if len(" ".join(remaining)) >= 2 else ""
    if party_type or lookup.capability in LISTABLE_READS:
        updates["limit"] = 10
    return with_arguments(lookup, **updates), party_type, notes


def execute_read(db, identity, lookup: ReadLookup):
    """Chat reads tolerate how people ask: unknown store filters, plurals, typos and loose names stay bounded and read-only."""
    notes = []

    def run(request, party_type=None):
        try:
            found = execute_lookup(db, identity, request)
        except HTTPException as error:
            if request.arguments.store_id is None or error.status_code not in {403, 404, 422}:
                raise
            request = with_arguments(request, store_id=None)
            found = execute_lookup(db, identity, request)
            if "That store was not recognised, so all permitted stores are shown." not in notes:
                notes.append("That store was not recognised, so all permitted stores are shown.")
        if party_type:
            found = {**found, "items": [row for row in found["items"] if row.get("party_type") in {party_type, "both"}]}
        return found, request

    attempts = [(lookup, None, [])]
    if lookup.arguments.query:
        interpreted, party_type, meaning = interpret_lookup(lookup, business_today())
        if lookup.capability == "account_journal":
            # The journal is filtered by dates only; its search words can only be periods.
            attempts = [(with_arguments(interpreted, query=""), None, meaning)]
        elif not interpreted.arguments.query:
            # Only descriptive words ("customers", "today sales"): they are filters, not a name.
            attempts.insert(0, (interpreted, party_type, meaning))
        elif interpreted.arguments != lookup.arguments:
            attempts.append((interpreted, party_type, meaning))
    for index, (request, party_type, meaning) in enumerate(attempts):
        candidate, request = run(request, party_type)
        if index == 0 or candidate["items"]:
            result, lookup, chosen = candidate, request, meaning
        if candidate["items"]:
            break
    notes.extend(chosen)
    query = lookup.arguments.query
    if not result["items"] and query and lookup.capability != "account_journal":
        exact, prefixes = relaxed_queries(query)
        for candidate in exact:
            relaxed = execute_lookup(db, identity, with_arguments(lookup, query=candidate))
            if relaxed["items"]:
                result = relaxed
                break
        if not result["items"] and prefixes:
            found = {}
            for prefix in prefixes:
                for row in execute_lookup(db, identity, with_arguments(lookup, query=prefix))["items"]:
                    found.setdefault(json.dumps(row, default=str, sort_keys=True), row)
            ranked = sorted(((difflib.SequenceMatcher(None, query.lower(), row_title(row).lower()).ratio(), row)
                             for row in found.values()), key=lambda pair: -pair[0])
            close = [row for score, row in ranked if score >= 0.5][:lookup.arguments.limit]
            if close:
                result = {**result, "items": close, "more_matches": False}
        if not result["items"] and lookup.capability in LISTABLE_READS:
            result = execute_lookup(db, identity, with_arguments(lookup, query=""))
            if result["items"]:
                notes.append(f"Nothing is named “{query}”; all {lookup.capability} are listed instead.")
        elif result["items"]:
            notes.append(f"No exact match for “{query}”; closest matches shown.")
    result["query"] = lookup.arguments.query
    result["fallback_note"] = " ".join(notes)
    return result


READ_MARKER = "From your Tenali records"
LEGACY_READ_MARKER = "Verified Tenali lookup (read only):"
FIRST_FIELDS = ("current_balance", "stock_qty", "balance_quantity", "quantity", "total", "balance_amount", "amount",
                "outstanding", "collection_status", "payment_status", "status")
HIDDEN_FIELDS = {"id", "period_key", "is_draft", "movement_quantity", "movement_count", "difference",
                 "missing_document_references"}
MONEY_WORDS = ("amount", "balance", "total", "price", "cost", "inflow", "outflow", "value", "outstanding", "mrp")
COUNT_WORDS = ("qty", "quantity", "stock", "count", "difference", "references")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def is_read_answer(content):
    return READ_MARKER + " — " in content or LEGACY_READ_MARKER in content


def is_money(key):
    return any(word in key for word in MONEY_WORDS) and not any(word in key for word in COUNT_WORDS)


def rupees(value):
    """Indian digit grouping (1,23,456.00)."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    sign, (whole, fraction) = "-" if amount < 0 else "", f"{abs(amount):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    while len(head) > 2:
        tail, head = head[-2:] + "," + tail, head[:-2]
    return f"{sign}₹{head + ',' if head else ''}{tail}.{fraction}"


def display_value(key, value):
    if isinstance(value, bool):
        return "yes" if value else "no"
    text_value = str(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text_value[:10]) and (len(text_value) == 10 or text_value[10] in "T "):
        year, month, day = text_value[:10].split("-")
        return f"{int(day)} {MONTHS[int(month) - 1]} {year}"
    number = value if isinstance(value, (Decimal, int, float)) else None
    if isinstance(value, str) and is_money(key) and re.fullmatch(r"-?\d+(\.\d+)?", value):
        number = Decimal(value)
    if number is not None:
        if is_money(key):
            return rupees(number)
        exact = Decimal(str(number))
        return format(exact.normalize(), "f") if exact == exact.to_integral() else text_value
    if key.endswith("status") or key == "direction":
        return text_value.replace("_", " ").lower()
    return text_value


def field_label(key):
    return key.removeprefix("is_").replace("_", " ")


def readable_row(row):
    title = row_title(row)
    keys = [key for key in FIRST_FIELDS if key in row] + [key for key in row if key not in FIRST_FIELDS]
    details = []
    for key in keys:
        value = row[key]
        if (value in (None, "") or value is False or key in HIDDEN_FIELDS or key.endswith("_id")
                or str(value) == title):
            continue
        details.append(field_label(key) if value is True else f"{field_label(key)} {display_value(key, value)}")
    return "• " + ": ".join(part for part in (title, " · ".join(details)) if part)


CAPABILITY_TITLES = {"reconciliation": "Stock by store", "reorder": "Low stock", "account_journal": "Account entries",
                     "hsn": "HSN codes", "parties": "Customers & vendors"}


def readable_lookup(result, budget: int) -> str:
    """Plain-language facts for people; values are data only, never instructions."""
    count = len(result["items"])
    title = CAPABILITY_TITLES.get(result["capability"], result["capability"].replace("_", " ").capitalize())
    heading = f"{READ_MARKER} — {title}"
    if result.get("query"):
        heading += f" matching “{result['query']}”"
    heading += f" ({count}{'+' if result.get('more_matches') else ''})"
    lines = [readable_row(row) for row in result["items"]] or ["• No matching records."]
    footer = [result["fallback_note"]] if result.get("fallback_note") else []
    if count > 1 and not result.get("more_matches"):
        # Complete (non-truncated) result sets can be summed exactly.
        for key in ("current_balance", "total", "balance_amount", "amount", "stock_qty", "balance_quantity"):
            values = [row.get(key) for row in result["items"]]
            if all(isinstance(value, (Decimal, int)) and not isinstance(value, bool) for value in values):
                label = "Total" if key == "total" else f"Total {field_label(key)}"
                footer.append(f"{label}: {display_value(key, sum(values))}")
                break
    if result.get("more_matches"):
        footer.append("More records match; ask with a narrower name, store or date.")
    limited = False
    while len(lines) > 1 and len("\n".join([heading, *lines, *footer])) > budget - 80:
        lines.pop()
        limited = True
    if limited:
        footer.insert(0, "Showing the first few only; narrow your question to see more.")
    return "\n\n" + "\n".join([heading, *lines, *footer])[:max(0, budget - 40)]
