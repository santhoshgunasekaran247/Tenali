"""Bounded business-state reads through existing services, without schema fallback writes."""
from fastapi import HTTPException

from app.ai.schemas import BusinessLookupArguments, COMPANY_LEDGER_KEYS
from app.services.access import allowed_stores
from app.services.accounts_service import AccountsService
from app.services.billing_service import BillingService
from app.services.collections_service import CollectionsService
from app.services.inventory_service import InventoryService
from app.services.purchases_service import PurchasesService
from app.services.refund_settlements import RefundSettlementsService
from app.services.runtime_schema import managed_schema
from app.services.settlements_service import SettlementsService
from app.services.stores_service import get_store


def business_lookup(db, identity: dict, key: str, args: BusinessLookupArguments) -> dict:
    permitted = allowed_stores(identity)
    if key in COMPANY_LEDGER_KEYS and permitted is not None:
        raise HTTPException(403, "Company-wide ledger reads require unrestricted store access")
    if not managed_schema(db):
        raise HTTPException(503, "AI business reads require a migrated database; no runtime schema changes are allowed")
    company = str(identity["company_id"])
    db.info["tenant_context"] = identity
    store = str(args.store_id) if args.store_id else None
    if store:
        get_store(db, company, store, require_active=False)
    if permitted == [] and key in {"reorder", "reconciliation"}:
        return {"items": [], "note": "No stores are permitted for this member; no inventory-state records are available."}
    limit = args.limit + 1
    status = None if args.status == "CANCELLED" else args.status
    if key == "accounts":
        result = AccountsService(db).account_tally(company, as_of=args.as_of.isoformat() if args.as_of else None,
                                                   search=args.query, limit=limit)
        note = f"Balances as of {result['as_of']}; all posted inflows/outflows including reversals. No company-wide total is supplied."
    elif key == "transactions":
        result = AccountsService(db).list_transactions(
            company, search=args.query, limit=limit,
            from_date=args.from_date.isoformat() if args.from_date else None,
            to_date=args.to_date.isoformat() if args.to_date else None)
        note = "Posted ledger entries by transaction date, including reversals. A reversed original is not an additional current payment."
    elif key == "invoices":
        result = BillingService(db).list_invoices(company, collection_status=status, store_id=store,
            cancelled_only=args.status == "CANCELLED", summary_only=True, search=args.query, limit=limit,
            from_date=args.from_date, to_date=args.to_date)
        note = "Current invoice/collection state; date filters use invoice date. Cancelled documents are not active sales."
    elif key == "purchases":
        result = PurchasesService(db).list_purchases(company, payment_status=status, store_id=store,
            cancelled_only=args.status == "CANCELLED", summary_only=True, search=args.query, limit=limit,
            from_date=args.from_date, to_date=args.to_date)
        note = "Current bill payment/receipt state; date filters use purchase date. Cancelled bills are not active purchases."
    elif key == "receivables":
        result = CollectionsService(db).list_receivables(company, status=status, store_id=store,
            permitted_stores=permitted, search=args.query, limit=limit, from_date=args.from_date, to_date=args.to_date)
        note = "Current receivable balances; date filters use due date. Store-restricted reads exclude standalone receivables with no invoice store."
    elif key == "refunds":
        result = RefundSettlementsService(db).list(status, store_id=store, permitted_stores=permitted,
            include_summary=False, search=args.query, limit=limit, from_date=args.from_date, to_date=args.to_date)
        note = "Refund settlement state; date filters use creation date. PAY_CUSTOMER is money owed to a customer; RECEIVE_VENDOR is money due back from a vendor. No company-wide summary."
    elif key == "borrowings":
        result = SettlementsService(db).summarize_borrowings(company, search=args.query, limit=limit)
        note = "Current party borrowing totals exclude reversed entries; positive outstanding means money owed to that party. Not historical as-of balances."
    elif key == "reorder":
        result = InventoryService(db, company).search_reorder_alerts(args.query, limit, store)
        note = "Configured reorder thresholds compared with permitted-store quantities; base product includes all variants. This scoped reminder can differ from the company-wide reminder."
    elif key == "reconciliation":
        result = InventoryService(db, company).stock_reconciliation(store_id=store, search=args.query, limit=limit)
        note = "Per-store/product/variant balance minus signed movement quantity; includes zero differences. Missing document references are separate from quantity differences."
    elif key == "period_locks":
        result = AccountsService(db).list_period_locks(company, as_of=args.as_of, search=args.query, limit=limit,
                                                      from_date=args.from_date, to_date=args.to_date)
        note = "Currently active locks only; date ranges overlap lock periods. as_of checks whether a date is currently locked, not historical lock state. Missing matches do not certify posting eligibility."
    else:
        raise HTTPException(422, "Business read adapter is not deployed")
    return {"items": result["items"], "note": note}
