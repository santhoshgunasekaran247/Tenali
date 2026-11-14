"""Business adapters use the caller's transaction; they never commit it."""
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import text

from app.ai.actions import PurchaseBundleDraft
from app.schemas.accounts import BusinessPaymentCreate
from app.schemas.billing import InvoiceCreate
from app.schemas.collections import ReceivablePaymentCreate
from app.schemas.inventory import ProductInput, StockAdjustment, StockTransferCreate
from app.schemas.parties import PartyCreate, PartyUpdate
from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate
from app.services.accounts_service import AccountsService
from app.services.billing_service import BillingService
from app.services.collections_service import CollectionsService
from app.services.commerce_stock import active_hsn, purchase_line_totals, resolve_product_lines
from app.services.inventory_service import InventoryService
from app.services.invoice_document import build_invoice_document
from app.services.masters_service import MastersService
from app.services.parties_service import PartiesService
from app.services.purchases_service import PurchasesService
from app.services.stores_service import get_store, stock_store
from app.services.document_cancellation import Cancellation, cancel_document
from app.services.transaction_deletion import TransactionDeletionService
from app.services.access import check_module


def operational_preview(db, company, action, target, values):
    from app.ai.operations_writes import OPERATIONS_ACTIONS, preview
    if action in OPERATIONS_ACTIONS:
        return preview(db, company, action, target, values)
    if action in {"product_create", "product_update"}:
        return InventoryService(db, company).preview_product(ProductInput.model_validate(values), str(target) if target else None)
    if action in {"expense_create", "business_payment_create"}:
        account = db.execute(text("select nickname,party_id,is_company_account from accounts where id=:id and company_id=:company"),
                             {"id": values["from_account_id"], "company": company}).mappings().one()
        borrowing = not account["is_company_account"] and values["create_borrowing"]
        if borrowing and not account["party_id"]:
            raise HTTPException(422, "Automatic borrowing requires a party-linked non-company account.")
        return {"account_name": account["nickname"], "account_debit": values["amount"],
                "creates_borrowing": borrowing, "borrowing_party_id": str(account["party_id"]) if borrowing else None,
                "settles_purchase_or_invoice": False}
    if action in {"purchase_payment", "collection_payment"}:
        table = "purchases" if action == "purchase_payment" else "receivables"
        row = db.execute(text(f"select * from {table} where id=:id and company_id=:company for update"),
                         {"id": str(target), "company": company}).mappings().one()
        due = Decimal(str(row["total"] if table == "purchases" else row["amount_due"])) - Decimal(
            str(row["amount_paid"] if table == "purchases" else row["amount_received"]))
        if Decimal(values["amount"]) > due or row["status"] in {"CANCELLED", "BAD_DEBT", "SETTLED"}:
            raise HTTPException(422, "Payment exceeds the current balance or this record cannot receive payments.")
        source = row["purchase_date"] if table == "purchases" else None
        if source and values["payment_date"] and values["payment_date"] < str(source):
            raise HTTPException(422, "Payment cannot precede the purchase date.")
        return {"balance_before": str(due), "payment": values["amount"],
                "balance_after": str(due - Decimal(values["amount"]))}
    if action in {"stock_adjust", "stock_transfer"}:
        changes = {}
        if action == "stock_adjust":
            changes[(values["store_id"], str(target), values["variant_id"])] = Decimal(values["quantity"]) * (1 if values["direction"] == "IN" else -1)
        else:
            if values["from_store_id"] == values["to_store_id"]:
                raise HTTPException(422, "Choose two different stock stores.")
            for line in values["lines"]:
                for store, direction in [(values["from_store_id"], -1), (values["to_store_id"], 1)]:
                    key = (store, str(line["product_id"]), line["variant_id"])
                    changes[key] = changes.get(key, Decimal("0")) + Decimal(line["quantity"]) * direction
        return {"stock_changes": stock_preview(db, company, changes)}
    return {"operation": action, "target": str(target) if target else "New record",
            "fields": values, "warning": "Existing business validation runs again at submission."}


def stock_preview(db, company, changes):
    from app.services.shop_stock import reserved_stock
    rows = []
    for (store, product, variant), delta in sorted(changes.items(), key=lambda item: str(item[0])):
        stock_store(db, company, store)
        db.execute(text("select id from products where id=:id and company_id=:company for update"),
                   {"id": product, "company": company})
        current = db.execute(text("""select quantity from stock_balances where company_id=:company and store_id=:store
            and product_id=:product and variant_id is not distinct from cast(:variant as uuid) for update"""),
            {"company": company, "store": store, "product": product, "variant": variant}).scalar_one_or_none() or Decimal("0")
        reserved = reserved_stock(db, company, product, variant, store)
        after = current + delta
        if after < 0 or (delta < 0 and after < reserved):
            raise HTTPException(422, "The operation would consume unavailable or reserved stock.")
        names = db.execute(text("""select (select name from stores where id=:store and company_id=:company) as store_name,
            (select name from products where id=:product and company_id=:company) as product_name"""),
            {"company": company, "store": store, "product": product}).mappings().one()
        rows.append({"store_id": store, "product_id": product, "variant_id": variant, "current": str(current),
                     "change": str(delta), "after": str(after), "reserved": str(reserved), **names})
    return rows


def destructive_preview(db, company, action, target, values):
    from app.ai.operations_writes import OPERATIONS_ACTIONS, preview
    if action in OPERATIONS_ACTIONS:
        return preview(db, company, action, target, values)
    if action == "product_delete":
        return InventoryService(db, company).preview_product_deletion(str(target))
    if action == "transaction_delete":
        report = TransactionDeletionService(db, company).preview(values["kind"], str(values["record_id"]), values["cascade"])
        if not report["can_delete"]:
            raise HTTPException(409, "; ".join(report["blockers"]) or "Review and explicitly include dependent records.")
        return report
    kind = "invoice" if action == "invoice_cancel" else "purchase"
    table = "invoices" if kind == "invoice" else "purchases"
    row = db.execute(text(f"select * from {table} where id=:id and company_id=:company for update"),
                     {"id": str(target), "company": company}).mappings().one()
    if row["status"] == "CANCELLED":
        raise HTTPException(409, "This document is already cancelled.")
    if values["cancellation_date"] < str(row[f"{kind}_date"]):
        raise HTTPException(422, "Cancellation date cannot precede the document.")
    if kind == "invoice":
        from app.services.collection_ledger import lock_invoice_receivables, receipt_totals
        invoice, receivable = lock_invoice_receivables(db, company, str(target))
        paid, _ = receipt_totals(db, company, receivable, invoice)
        lines = (row["document_data"] or {}).get("lines", [])
    else:
        from app.services.purchase_ledger import purchase_payment_totals
        paid, _ = purchase_payment_totals(db, company, dict(row))
        lines = row["line_items"] if row["receipt_status"] == "RECEIVED" and row["receipt_type"] != "SERVICE" else []
    if paid and not values["reverse_payments"]:
        raise HTTPException(422, "Explicitly choose payment reversals; they produce pending refunds, not immediate cash refunds.")
    from app.services.commerce_stock import booked_store
    store = booked_store(db, company, "invoice" if kind == "invoice" else "purchase_receipt", str(target)) or str(row["store_id"])
    changes = {}
    for line in lines:
        if line.get("product_id"):
            key = (store, str(line["product_id"]), str(line["variant_id"]) if line.get("variant_id") else None)
            changes[key] = changes.get(key, Decimal("0")) + Decimal(str(line["quantity"])) * (1 if kind == "invoice" else -1)
    return {"confirm_text": row["invoice_number"] if kind == "invoice" else row["voucher_number"],
            "pending_refunds": str(paid), "refund_direction": "PAY_CUSTOMER" if kind == "invoice" else "RECEIVE_VENDOR",
            "stock_direction": "IN" if kind == "invoice" else "OUT", "stock_lines": lines,
            "stock_changes": stock_preview(db, company, changes),
            "warning": "Cancellation reverses document payments into pending refunds which must be settled separately."}


def document_preview(db, company, action, values):
    model = (PurchaseCreate if action == "purchase_create" else InvoiceCreate).model_validate(values)
    existing = [line for line in model.lines if not line.new_product]
    if action == "invoice_create" and any(line.new_product for line in model.lines):
        raise HTTPException(422, "Sales cannot create new inventory products.")
    if action == "purchase_create":
        model.receipt_type = PurchasesService(db)._normalize_receipt_type(model.receipt_type)
        for line in model.lines:
            if not line.new_product:
                continue
            if line.product_id or line.variant_id or not active_hsn(db, company, line.hsn):
                raise HTTPException(422, "New products require an active HSN and no existing product/variant ID.")
            name = " ".join(line.description.split())
            if db.execute(text("select 1 from products where company_id=:company and lower(name)=lower(:name) and is_active"),
                          {"company": company, "name": name}).first():
                raise HTTPException(409, f"{name} already exists. Select the existing product.")
            line.description = name
        resolve_product_lines(db, company, existing, str(model.vendor_party_id), allow_drafts=True, persist_hsn=False)
        MastersService(db).apply_hsn_rates(model.lines, company)
        lines = purchase_line_totals(model)
        stock_store(db, company, str(model.store_id))
    else:
        resolve_product_lines(db, company, existing, persist_hsn=False)
        MastersService(db).apply_hsn_rates(model.lines, company)
        seller = dict(db.execute(text("""select company_name,address,gst_number,gst_registered,udyam_number,
            logo_url,phone,email,website,invoice_settings,prices_include_gst from companies where id=:company for share"""),
            {"company": company}).mappings().one())
        customer = dict(db.execute(text("select id,legal_name,gst_number,address from parties where company_id=:company and id=:id for share"),
            {"company": company, "id": str(model.customer_party_id)}).mappings().one())
        store = get_store(db, company, str(model.store_id))
        model.stock_store_id = UUID(str(model.stock_store_id or store["fulfilment_store_id"] or store["id"]))
        stock_store(db, company, str(model.stock_store_id))
        doc = build_invoice_document(model, seller, customer, store, bool(seller["prices_include_gst"]))
        model.subtotal, model.gst_total, model.total = (Decimal(doc[key]) for key in ("subtotal", "gst_total", "total"))
        for line, computed in zip(model.lines, doc["lines"]):
            line.gst_rate = Decimal(computed["gst_rate"])
            line.price_includes_gst = computed["price_includes_gst"]
        lines = doc["lines"]
    paid = model.amount_paid if isinstance(model, PurchaseCreate) else model.amount_received
    if paid > model.total or (paid and (not model.account_id or not (model.payment_mode or "").strip())):
        raise HTTPException(422, "Paid/received amount must not exceed the computed total and requires account and payment mode.")
    normalized = model.model_dump(mode="json", exclude={"idempotency_key", "attachments"})
    changes = {}
    hsn_updates = {}
    store_id = str(model.store_id if isinstance(model, PurchaseCreate) else model.stock_store_id)
    for line in model.lines:
        if line.product_id:
            product = db.execute(text("select hsn_code from products where id=:id and company_id=:company"),
                                 {"id": str(line.product_id), "company": company}).mappings().one()
            if not product["hsn_code"]:
                hsn_updates[str(line.product_id)] = line.hsn
        if line.product_id and (not isinstance(model, PurchaseCreate) or (model.received_now and model.receipt_type != "SERVICE")):
            key = (store_id, str(line.product_id), str(line.variant_id) if line.variant_id else None)
            changes[key] = changes.get(key, Decimal("0")) + line.quantity * (1 if isinstance(model, PurchaseCreate) else -1)
    return normalized, {"subtotal": str(model.subtotal), "gst_total": str(model.gst_total), "total": str(model.total),
                        "paid_or_received": str(paid), "lines": lines,
                        "stock_store_id": str(model.store_id if isinstance(model, PurchaseCreate) else model.stock_store_id),
                        "goods_received": model.received_now and model.receipt_type != "SERVICE" if isinstance(model, PurchaseCreate) else True,
                        "document": doc if isinstance(model, InvoiceCreate) else None,
                        "stock_changes": stock_preview(db, company, changes),
                        "product_hsn_updates": hsn_updates,
                        "new_products": [line.description for line in model.lines if line.new_product]}


def purchase_bundle_preview(db, company: str, values: dict, draft_id: str):
    model = PurchaseBundleDraft.model_validate(values)
    identity = db.info.get("tenant_context")
    check_module(identity, "/parties")
    check_module(identity, "/inventory")
    if model.fully_paid:
        check_module(identity, "/accounts")
    if not model.vendor_name.strip() or not model.product_name.strip():
        raise HTTPException(422, "Vendor and product names are required.")
    if model.quantity is None or model.rate is None:
        raise HTTPException(422, "Quantity and purchase rate are required.")
    if not model.purchase_date:
        raise HTTPException(422, "Purchase date is required.")
    if model.price_includes_gst is None:
        raise HTTPException(422, "Confirm whether the unit rate includes GST.")
    if model.fully_paid is None:
        raise HTTPException(422, "Confirm whether the purchase is fully paid.")
    if model.received_now is None:
        raise HTTPException(422, "Confirm whether the goods have been received.")
    if not model.hsn:
        raise HTTPException(422, "HSN/SAC is required. Choose an active code from Master Data.")
    hsn_rate = db.execute(text("select gst_rate from hsn_masters where company_id=:company and code=:code and is_active"),
                          {"company": company, "code": model.hsn}).scalar_one_or_none()
    if hsn_rate is None:
        raise HTTPException(422, "HSN/SAC must be an active code from Master Data.")
    if model.gst_rate is not None and Decimal(str(hsn_rate)) != model.gst_rate:
        raise HTTPException(422, f"The selected HSN/SAC uses GST {hsn_rate}%, not {model.gst_rate}%. Review the code or rate.")
    if not model.store_id:
        if not model.store_name.strip():
            raise HTTPException(422, "Receiving store is required.")
        stores = db.execute(text("""select id from stores where company_id=:company and is_active
            and (lower(name)=lower(:name) or lower(code)=lower(:name)) order by id limit 3"""),
            {"company": company, "name": model.store_name.strip()}).scalars().all()
        if len(stores) != 1:
            raise HTTPException(422, "Could not uniquely find the receiving store. Choose an exact permitted store name.")
        model.store_id = UUID(str(stores[0]))
    store = stock_store(db, company, str(model.store_id))
    if model.fully_paid and not model.account_id:
        if not model.account_name.strip():
            raise HTTPException(422, "Payment account is required for this fully paid purchase.")
        accounts = db.execute(text("""select id from accounts where company_id=:company and is_active
            and lower(nickname)=lower(:name) order by id limit 3"""),
            {"company": company, "name": model.account_name.strip()}).scalars().all()
        if len(accounts) != 1:
            raise HTTPException(422, "Could not uniquely find the payment account. Choose an exact account name.")
        model.account_id = UUID(str(accounts[0]))
    account = (db.execute(text("select id from accounts where id=:id and company_id=:company and is_active"),
                         {"id": str(model.account_id), "company": company}).first() if model.account_id else None)
    if model.fully_paid and not account:
        raise HTTPException(422, "Select an active payment account from this workspace.")
    if model.fully_paid and not model.payment_mode.strip():
        raise HTTPException(422, "Payment mode is required for a fully paid purchase.")

    vendor_id = model.vendor_party_id
    vendor_created = False
    if vendor_id:
        vendor = db.execute(text("""select id from parties where id=:id and company_id=:company and is_active
            and party_type in ('vendor','customer_vendor')"""),
            {"id": str(vendor_id), "company": company}).scalar_one_or_none()
        if not vendor:
            raise HTTPException(422, "Selected party is not an active vendor in this workspace.")
        vendor_id = UUID(str(vendor))
    else:
        vendors = db.execute(text("""select id from parties where company_id=:company and is_active
            and party_type in ('vendor','customer_vendor') and
            (lower(legal_name)=lower(:name) or lower(coalesce(nickname,''))=lower(:name)) order by id limit 3"""),
            {"company": company, "name": model.vendor_name.strip()}).scalars().all()
        if len(vendors) > 1:
            raise HTTPException(422, "Several vendors match this name. Refine the vendor name before continuing.")
        if vendors:
            vendor_id = UUID(str(vendors[0]))
        elif not model.create_vendor_if_missing:
            raise HTTPException(422, "Vendor was not found. Allow creation or provide an existing vendor name.")
        else:
            vendor_created = True
            vendor_id = uuid5(NAMESPACE_URL, f"tenali-ai-purchase-vendor:{draft_id}:{model.vendor_name.strip().casefold()}")

    line = {"description": model.product_name.strip(), "hsn": model.hsn, "quantity": model.quantity,
            "rate": model.rate, "gst_rate": model.gst_rate or Decimal("0"),
            "price_includes_gst": model.price_includes_gst, "new_product": True}
    purchase = PurchaseCreate.model_validate({
        "vendor_party_id": vendor_id, "store_id": model.store_id, "purchase_date": model.purchase_date,
        "account_id": model.account_id, "payment_mode": model.payment_mode.strip() or None,
        "amount_paid": Decimal("0"), "received_now": model.received_now,
        "receipt_type": "PRODUCT", "lines": [line],
    })
    normalized, calculation = document_preview(db, company, "purchase_create", purchase.model_dump(mode="json"))
    if model.fully_paid:
        normalized["amount_paid"] = calculation["total"]
        normalized, calculation = document_preview(db, company, "purchase_create", normalized)
    bundle = model.model_dump(mode="json")
    bundle.update(store_id=None, account_id=None, vendor_party_id=None)
    calculation.update({
        "workflow": [
            {"step": "vendor", "operation": "create" if vendor_created else "reuse", "name": model.vendor_name},
            {"step": "product", "operation": "create draft product", "name": model.product_name,
             "selling_price": str(model.selling_price) if model.selling_price is not None else None},
            {"step": "purchase", "date": model.purchase_date.isoformat(), "total": calculation["total"],
             "paid": calculation["paid_or_received"], "payment_mode": model.payment_mode},
            {"step": "stock receipt", "operation": "IN" if normalized["received_now"] else "pending",
             "quantity": str(model.quantity), "store": store["name"]},
        ],
        "vendor_to_create": vendor_created,
        "purchase_payload": normalized,
    })
    return bundle, calculation


def apply_action(db, company: str, action: str, target: str | None, values: dict, key: str, preview=None, confirm_text=None):
    if action == "business_payment_create":
        return AccountsService(db).create_business_payment(company, BusinessPaymentCreate.model_validate({**values, "idempotency_key": key}), commit=False)
    if action in {"report_export", "gst_reconcile"}:
        from app.ai.reports import apply as apply_report
        return apply_report(db, company, action, values, key, preview)
    from app.ai.operations_writes import OPERATIONS_ACTIONS, apply
    if action in OPERATIONS_ACTIONS:
        return apply(db, company, action, target, values)
    payload = {**values, "idempotency_key": key}
    if action == "expense_create":
        return AccountsService(db).create_business_payment(company, BusinessPaymentCreate.model_validate(payload), commit=False)
    if action == "purchase_create":
        return PurchasesService(db).create_purchase(company, PurchaseCreate.model_validate(payload), commit=False)
    if action == "purchase_bundle_create":
        purchase_values = dict(preview["purchase_payload"])
        vendor_created = bool(preview["vendor_to_create"])
        if vendor_created:
            name = " ".join(values["vendor_name"].split())
            db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key,0))"),
                       {"key": f"purchase-vendor:{company}:{name.casefold()}"})
            vendors = db.execute(text("""select id from parties where company_id=:company and is_active
                and party_type in ('vendor','customer_vendor') and
                (lower(legal_name)=lower(:name) or lower(coalesce(nickname,''))=lower(:name)) order by id limit 2"""),
                {"company": company, "name": name}).scalars().all()
            if len(vendors) > 1:
                raise HTTPException(409, "More than one matching vendor exists. Review the vendor before submitting.")
            if vendors:
                vendor_id = str(vendors[0])
                vendor_created = False
            else:
                vendor = PartiesService(db).create(company, PartyCreate(party_type="vendor", legal_name=name), commit=False)
                vendor_id = str(vendor["id"])
        else:
            vendor_id = str(purchase_values["vendor_party_id"])
        purchase_values.update(vendor_party_id=vendor_id, idempotency_key=key)
        product_name = " ".join(values["product_name"].split())
        prices = ({product_name.casefold(): Decimal(str(values["selling_price"]))}
                  if values.get("selling_price") is not None else {})
        purchase = PurchasesService(db).create_purchase(company, PurchaseCreate.model_validate(purchase_values),
            commit=False, new_product_selling_prices=prices)
        return {**purchase, "vendor_created": vendor_created,
                "product_name": product_name, "stock_received": bool(purchase.get("receipt_status") == "RECEIVED")}
    if action == "invoice_create":
        return BillingService(db).create_invoice(company, InvoiceCreate.model_validate(payload), commit=False)
    if action == "party_create":
        return PartiesService(db).create(company, PartyCreate.model_validate(values), commit=False)
    if action == "product_create":
        return InventoryService(db, company).save_product(ProductInput.model_validate(values), commit=False)
    if action == "stock_transfer":
        return InventoryService(db, company).transfer_stock(StockTransferCreate.model_validate(payload), commit=False)
    if action == "transaction_delete":
        return TransactionDeletionService(db, company).delete(values["kind"], str(values["record_id"]), preview["token"],
            confirm_text, values["reason"], values["cascade"], commit=False)
    if target is None:
        raise HTTPException(422, "Select an existing target for this operation.")
    if action == "party_update":
        return PartiesService(db).update(target, PartyUpdate.model_validate(values), company, commit=False)
    if action == "product_update":
        return InventoryService(db, company).save_product(ProductInput.model_validate(values), target, commit=False)
    if action == "stock_adjust":
        return InventoryService(db, company).adjust_stock(target, StockAdjustment.model_validate(payload), commit=False)
    if action == "purchase_payment":
        return PurchasesService(db).add_purchase_payment(target, company, PurchasePaymentCreate.model_validate(payload), commit=False)
    if action == "collection_payment":
        return CollectionsService(db).collect_receivable(target, company, ReceivablePaymentCreate.model_validate(payload), commit=False)
    if action in {"invoice_cancel", "purchase_cancel"}:
        return cancel_document(db, company, "invoice" if action == "invoice_cancel" else "purchase",
                               target, Cancellation.model_validate(values), commit=False)
    if action == "product_delete":
        return InventoryService(db, company).delete_product(target, commit=False)
    raise ValueError(f"No execution adapter for {action}")
