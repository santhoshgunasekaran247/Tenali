"""Additional Operations adapters; previews do not persist business changes."""
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import text

from app.ai.actions import ACTIONS
from app.schemas.accounts import AccountCreate, AccountUpdate, AccountTransactionCreate, TransactionReverseCreate
from app.schemas.collections import ReceivableCreate, ReceivableStatusUpdate, ReceivableReminderUpdate
from app.schemas.inventory import (VariantInput, VendorOfferInput, BulkVendorMapping, ProductMerge,
                                  ExternalMovementSource, ReorderReminder)
from app.schemas.purchases import PurchaseReceiptConfirm
from app.schemas.settlements import BorrowingEntryCreate
from app.services.access import check_module
from app.services.accounts_service import AccountsService
from app.services.collection_ledger import lock_receivable, receipt_totals, payment_status
from app.services.collections_service import CollectionsService
from app.services.inventory_service import InventoryService
from app.services.period_lock_service import assert_period_open
from app.services.purchases_service import PurchasesService
from app.services.refund_settlements import RefundSettle, RefundSettlementsService
from app.services.settlements_service import SettlementsService
from app.services.borrowing_ledger import LEDGER_SIDE, OPENING_DIRECTIONS, SETTLING_DIRECTIONS, available_repayment

OPERATIONS_ACTIONS = set(ACTIONS) - {
    "expense_create", "purchase_create", "purchase_bundle_create", "invoice_create", "party_create", "party_update",
    "product_create", "product_update", "stock_adjust", "stock_transfer", "purchase_payment",
    "collection_payment", "invoice_cancel", "purchase_cancel", "product_delete", "transaction_delete",
}


def record(db, company, table, target):
    # Only adapter-owned constant names reach this helper.
    if table not in {"accounts", "account_transactions", "refund_settlements", "products",
                     "product_variants", "vendor_contributions", "purchases", "stock_movements"}:
        raise ValueError("Unsupported Operations reference")
    if table in {"product_variants", "vendor_contributions"}:
        query = f"select r.* from {table} r join products p on p.id=r.product_id where r.id=:id and p.company_id=:company"
    else:
        query = f"select * from {table} where id=:id and company_id=:company"
    row = db.execute(text(query), {"id": str(target), "company": company}).mappings().first()
    if not row:
        raise HTTPException(422, "The selected Operations record does not belong to this workspace.")
    return dict(row)


def preview(db, company, action, target, values):
    if action == "business_payment_create":
        from app.ai.business_writes import operational_preview
        if values["purpose"] in {"purchase", "billing"} and not values["related_party_id"]:
            raise HTTPException(422, "Standalone purchase/billing outflows require the related party.")
        return operational_preview(db, company, "expense_create", target, values)
    if action in {"report_export", "gst_reconcile"}:
        from app.ai.reports import generate
        return generate(db, company, action, values)[1]
    from app.ai.business_writes import stock_preview
    identity = db.info["tenant_context"]
    inventory = InventoryService(db, company)
    result = {"operation": action, "fields": values}
    if action in {"account_create", "account_update"}:
        current = record(db, company, "accounts", target) if target else {}
        projected = {**current, **values}
        AccountsService(db)._assert_company_account_uniqueness(company, projected["is_company_account"],
                                                              str(target) if target else None)
        if current and "opening_balance" in values and Decimal(str(values["opening_balance"])) != current["opening_balance"]:
            if db.execute(text("""select 1 from account_transactions where company_id=:company
                and (from_account_id=:id or to_account_id=:id) limit 1"""),
                {"company": company, "id": str(target)}).first():
                raise HTTPException(422, "Cannot change opening balance after transactions exist. Post an adjustment instead.")
        result["before"] = {name: current.get(name) for name in values} if current else None
    elif action == "account_transaction_create":
        source, destination = values["from_account_id"], values["to_account_id"]
        if not source and not destination or source and source == destination:
            raise HTTPException(422, "Select one account for inflow/outflow, or two different accounts for transfer.")
        result["account_changes"] = [{"account_id": account, "change": str(Decimal(values["amount"]) * sign)}
                                     for account, sign in ((source, -1), (destination, 1)) if account]
        result["ledger_effect"] = "Manual entry only; does not settle invoices, purchases or borrowings."
    elif action == "account_transaction_reverse":
        original = record(db, company, "account_transactions", target)
        if original["reversal_of_transaction_id"] or db.execute(text("""select 1 from account_transactions
            where company_id=:company and reversal_of_transaction_id=:id"""),
            {"company": company, "id": str(target)}).first():
            raise HTTPException(422, "Reversal transactions and already-reversed transactions cannot be reversed.")
        if values["transaction_date"] < str(original["transaction_date"]):
            raise HTTPException(422, "Reversal date cannot precede the original transaction.")
        result.update(amount=str(original["amount"]), original_date=str(original["transaction_date"]),
                      source_type=original["source_type"], source_id=str(original["source_id"]) if original["source_id"] else None,
                      account_changes=[{"account_id": str(account), "change": str(original["amount"] * sign)}
                          for account, sign in ((original["from_account_id"], 1), (original["to_account_id"], -1)) if account],
                      ledger_effect="Existing linked receipt, purchase-payment or borrowing reversal effects run together; business-category payments retain their existing semantics.")
        borrowing = AccountsService(db)._lock_reversal_source(company, str(target), original)
        if borrowing:
            outstanding = available_repayment(db, company, str(borrowing["party_id"]), date.fromisoformat(values["transaction_date"]), borrowing["direction"])
            if borrowing["direction"] in OPENING_DIRECTIONS and borrowing["amount"] > outstanding:
                raise HTTPException(422, "Reverse linked repayments or collections before reversing this entry.")
            result["borrowing_effect"] = {"id": str(borrowing["id"]), "direction": borrowing["direction"],
                "outstanding_before": str(outstanding),
                "outstanding_after": str(outstanding + borrowing["amount"] * (-1 if borrowing["direction"] in OPENING_DIRECTIONS else 1))}
        if original["category"] not in {"business_purchase", "business_billing", "business_expense"}:
            source, source_id = original["source_type"], original["source_id"]
            if source in {"invoice", "receivable_payment"}:
                if source == "invoice":
                    from app.services.collection_ledger import lock_invoice_receivables
                    invoice, receivable = lock_invoice_receivables(db, company, str(source_id))
                else:
                    receivable_id = db.execute(text("select receivable_id from receivable_payments where id=:id and company_id=:company"),
                        {"id": source_id, "company": company}).scalar_one()
                    receivable, invoice = lock_receivable(db, company, str(receivable_id))
                if receivable:
                    paid, _ = receipt_totals(db, company, receivable, invoice)
                    result["collection_effect"] = {"receivable_id": str(receivable["id"]), "paid_before": str(paid),
                                                  "paid_after": str(paid - original["amount"])}
            elif source in {"purchase", "purchase_payment"}:
                from app.services.purchase_ledger import purchase_payment_totals
                document_id = source_id if source == "purchase" else db.execute(text(
                    "select purchase_id from purchase_payments where id=:id and company_id=:company"),
                    {"id": source_id, "company": company}).scalar_one()
                purchase = record(db, company, "purchases", document_id)
                paid, _ = purchase_payment_totals(db, company, purchase)
                result["purchase_effect"] = {"purchase_id": str(document_id), "paid_before": str(paid),
                                            "paid_after": str(paid - original["amount"])}
    elif action == "borrowing_create":
        if values["account_id"]:
            check_module(identity, "/accounts")
        if values["create_account_transaction"]:
            if not values["account_id"]:
                raise HTTPException(422, "Choose an account when posting the linked account transaction.")
        direction = values["direction"]
        amount = Decimal(values["amount"])
        outstanding = available_repayment(db, company, values["party_id"], date.fromisoformat(values["transaction_date"]), direction)
        if direction in SETTLING_DIRECTIONS and amount > outstanding:
            other = "repay" if direction == "collect" else "collect"
            other_outstanding = available_repayment(db, company, values["party_id"], date.fromisoformat(values["transaction_date"]), other)
            hint = (f" They owe you ₹{other_outstanding:.2f} from money you lent; if they paid you back, choose 'Collected back from them'."
                    if direction == "repay" and amount <= other_outstanding else
                    f" You owe them ₹{other_outstanding:.2f}; if you paid them back, choose 'Repaid to them'."
                    if direction == "collect" and amount <= other_outstanding else
                    " To give money as a loan, choose 'Lent to them'." if direction == "repay" else "")
            if direction == "collect":
                raise HTTPException(422, f"Collection exceeds what this party owes you (₹{outstanding:.2f}).{hint}")
            raise HTTPException(422, f"Repayment exceeds what you owe this party (₹{outstanding:.2f}).{hint}")
        inflow = 1 if direction in {"borrow", "collect"} else -1
        result.update(ledger="lent to party (party owes you)" if LEDGER_SIDE[direction] == "lend" else "borrowed from party (you owe them)",
                      outstanding_before=str(outstanding),
                      outstanding_after=str(outstanding + amount * (1 if direction in OPENING_DIRECTIONS else -1)),
                      account_change=str(amount * inflow) if values["create_account_transaction"] else "0",
                      no_account_entry=not values["create_account_transaction"])
    elif action == "refund_settle":
        check_module(identity, "/accounts")
        settlement = record(db, company, "refund_settlements", target)
        if settlement["status"] != "PENDING":
            raise HTTPException(409, "This refund is already settled.")
        reversal = record(db, company, "account_transactions", settlement["reversal_transaction_id"])
        original = record(db, company, "account_transactions", settlement["original_transaction_id"])
        when = date.fromisoformat(values["settled_on"])
        if not original["transaction_date"] <= when <= date.today():
            raise HTTPException(422, "Refund date must be between the original payment date and today.")
        assert_period_open(db, company, reversal["transaction_date"], "Settling a refund")
        result.update(amount=str(settlement["amount"]), direction=settlement["direction"],
                      existing_transaction_id=str(reversal["id"]), previous_account_id=str(reversal["from_account_id"] or reversal["to_account_id"]),
                      previous_date=str(reversal["transaction_date"]),
                      ledger_effect="Updates the existing pending reversal's account/date/mode. No additional transaction is inserted.")
    elif action == "receivable_create":
        if values["invoice_id"]:
            from app.services.collection_ledger import lock_invoice_receivables
            invoice, existing = lock_invoice_receivables(db, company, values["invoice_id"])
            if existing or invoice["status"] == "CANCELLED":
                raise HTTPException(422, "This invoice already has a receivable or is cancelled.")
            if str(invoice["customer_party_id"]) != values["party_id"] or invoice["total"] != Decimal(values["amount_due"]):
                raise HTTPException(422, "Receivable customer and amount must match the invoice.")
        result["money_received"] = "0"
    elif action in {"receivable_status", "receivable_reminder"}:
        receivable, invoice = lock_receivable(db, company, str(target))
        if invoice and invoice["status"] == "CANCELLED":
            raise HTTPException(422, "A cancelled invoice cannot change collection status or reminders.")
        received, _ = receipt_totals(db, company, receivable, invoice)
        derived = payment_status(Decimal(receivable["amount_due"]), received)
        if action == "receivable_status":
            if values["status"] == "BAD_DEBT":
                if not values["bad_debt_reason"] or derived == "SETTLED":
                    raise HTTPException(422, "Bad debt requires a reason and an unpaid balance.")
            elif values["status"] != derived:
                raise HTTPException(422, f"Status must match the payment ledger: {derived}.")
        elif derived not in {"UNPAID", "PARTIAL"} or receivable["status"] == "BAD_DEBT":
            raise HTTPException(422, "Reminders require a collectible receivable.")
        result.update(status_before=receivable["status"], ledger_status=derived, amount_received=str(received),
                      outstanding=str(Decimal(receivable["amount_due"]) - received), reminder_before=str(receivable["reminder_date"]) if receivable["reminder_date"] else None,
                      sends_customer_message=False)
    elif action == "purchase_receive":
        purchase = record(db, company, "purchases", target)
        if purchase["status"] == "CANCELLED" or purchase["receipt_status"] == "RECEIVED":
            raise HTTPException(409, "This purchase is cancelled or already received.")
        receipt_type = PurchasesService(db)._normalize_receipt_type(values["receipt_type"] or purchase["receipt_type"])
        changes = {}
        if receipt_type != "SERVICE":
            for line in purchase["line_items"]:
                if line.get("product_id"):
                    key = (str(purchase["store_id"]), str(line["product_id"]), str(line["variant_id"]) if line.get("variant_id") else None)
                    changes[key] = changes.get(key, Decimal("0")) + Decimal(str(line["quantity"]))
        result.update(receipt_type=receipt_type, stock_changes=stock_preview(db, company, changes), accounting_payment="0")
    elif action == "product_confirm":
        product = record(db, company, "products", target)
        if not product["is_draft"] or not product.get("hsn_code"):
            raise HTTPException(422, "Select a draft product with an HSN/SAC code before confirming.")
        result.update(name=product["name"], hsn_code=product["hsn_code"], stock_change="0", is_draft_after=False)
    elif action == "product_merge":
        draft = record(db, company, "products", target)
        destination = record(db, company, "products", values["target_product_id"])
        if str(target) == values["target_product_id"] or not draft["is_draft"] or not destination["is_active"]:
            raise HTTPException(422, "Merge a draft into a different active product.")
        if db.execute(text("select 1 from product_variants where product_id=:id limit 1"), {"id": str(target)}).first():
            raise HTTPException(422, "A draft with variants cannot be merged.")
        variant = values["target_variant_id"]
        if variant:
            selected = record(db, company, "product_variants", variant)
            if str(selected["product_id"]) != values["target_product_id"] or not selected["is_active"]:
                raise HTTPException(422, "Choose an active variant of the target product.")
        elif db.execute(text("select 1 from product_variants where product_id=:id and is_active limit 1"),
                        {"id": values["target_product_id"]}).first():
            raise HTTPException(422, "Choose the target variant receiving this draft's stock.")
        result["balances_moved"] = [dict(row) for row in db.execute(text("""select store_id,quantity from stock_balances
            where company_id=:company and product_id=:id order by store_id,id"""), {"company": company, "id": str(target)}).mappings()]
        result["dependencies"] = {table: db.execute(text(f"select count(*) from {table} where product_id=:id"),
                                  {"id": str(target)}).scalar_one()
                                  for table in ("stock_movements", "purchase_items", "invoice_items", "enquiries", "vendor_contributions")}
        result["dependency_hashes"] = {table: db.execute(text(f"""select md5(coalesce(
            string_agg(md5(row_to_json(r)::text),',' order by r.id),'')) from {table} r where product_id=:id"""),
            {"id": str(target)}).scalar_one() for table in result["dependencies"]}
        for table, column in (("purchases", "line_items"), ("stock_transfers", "lines")):
            result["dependency_hashes"][table] = db.execute(text(f"""select md5(coalesce(
                string_agg(md5({column}::text),',' order by id),'')) from {table}
                where company_id=:company and {column}::text like :reference"""),
                {"company": company, "reference": f"%{target}%"}).scalar_one()
        result["duplicate_vendor_offers_removed"] = db.execute(text("""select count(*) from vendor_contributions d
            where d.product_id=:draft and exists(select 1 from vendor_contributions t where t.product_id=:target
            and t.vendor_id=d.vendor_id and t.variant_id is not distinct from cast(:variant as uuid))"""),
            {"draft": str(target), "target": values["target_product_id"], "variant": variant}).scalar_one()
        result["removes_draft_product"] = True
        result["total_stock_change"] = "0"
    elif action in {"variant_create", "variant_update", "offer_create", "offer_update"}:
        product_id = values["product_id"]
        product = inventory.detail(product_id)
        if action.startswith("variant_"):
            current = record(db, company, "product_variants", target) if target else {}
            if current and str(current["product_id"]) != product_id:
                raise HTTPException(422, "The variant does not belong to this product.")
            fields = {key: value for key, value in values.items() if key != "product_id"}
            inventory._validate_item(fields, product_id, str(target) if target else None)
            if db.execute(text("""select 1 from product_variants where product_id=:product and is_active
                and id is distinct from cast(:id as uuid) and lower(coalesce(size,''))=lower(:size)
                and lower(coalesce(colour,''))=lower(:colour) and (:size<>'' or :colour<>'') limit 1"""),
                {"product": product_id, "id": str(target) if target else None, "size": fields["size"] or "", "colour": fields["colour"] or ""}).first():
                raise HTTPException(409, "An active variant with this size and colour already exists.")
            offers = next((item["offers"] for item in product["variants"] if str(item["id"]) == str(target)), [])
            projected = inventory._enrich({**current, **fields}, offers, Decimal("0"), product["preferred_vendor_id"], product)
            if projected["pricing_error"]:
                raise HTTPException(422, projected["pricing_error"])
            result.update(catalog_price=projected["catalog_price"], stock_change="0")
        else:
            inventory._vendor(values["vendor_id"])
            if values["variant_id"]:
                inventory._variant(product_id, values["variant_id"])
            current = record(db, company, "vendor_contributions", target) if target else {}
            if current and (str(current["product_id"]) != product_id or str(current["vendor_id"]) != values["vendor_id"]
                            or (str(current["variant_id"]) if current["variant_id"] else None) != values["variant_id"]):
                raise HTTPException(422, "An offer's product, variant and vendor cannot be changed.")
            if db.execute(text("""select 1 from vendor_contributions where product_id=:product and vendor_id=:vendor
                and variant_id is not distinct from cast(:variant as uuid) and id is distinct from cast(:id as uuid) limit 1"""),
                {"product": product_id, "vendor": values["vendor_id"], "variant": values["variant_id"], "id": str(target) if target else None}).first():
                raise HTTPException(409, "This vendor is already mapped; update the existing offer.")
            selected = next((item for item in product["variants"] if str(item["id"]) == values["variant_id"]), product)
            inherits_vendor = bool(values["variant_id"] and product.get("preferred_vendor_id"))
            becomes_preferred = not selected.get("preferred_vendor_id") and values["is_active"] and not inherits_vendor
            proposed_offers = [item for item in selected["offers"] if str(item["id"]) != str(target)]
            proposed_offers.append({**values, "vendor_active": True, "vendor_name": "Selected vendor"})
            proposed = inventory._enrich({**selected, "preferred_vendor_id": values["vendor_id"] if becomes_preferred else selected.get("preferred_vendor_id")},
                                         proposed_offers, Decimal("0"), product.get("preferred_vendor_id"), product)
            if proposed["pricing_error"]:
                raise HTTPException(422, proposed["pricing_error"])
            result.update(catalog_price=proposed["catalog_price"], automatically_preferred=becomes_preferred,
                          availability_is_owned_stock=False, stock_change="0")
        result["before"] = {key: current.get(key) for key in values if key != "product_id"} if current else None
    elif action == "vendor_bulk_map":
        inventory._vendor(values["vendor_id"])
        result["new_mappings"] = [product for product in sorted(set(values["product_ids"]))
            if not db.execute(text("select 1 from vendor_contributions where product_id=:product and vendor_id=:vendor and variant_id is null limit 1"),
                              {"product": product, "vendor": values["vendor_id"]}).first()]
        result["stock_change"] = "0"
    elif action in {"brand_create", "brand_update", "category_create", "category_update"}:
        table = "brands" if action.startswith("brand_") else "product_categories"
        if db.execute(text(f"""select 1 from {table} where company_id=:company and lower(name)=lower(:name)
            and id is distinct from cast(:id as uuid) limit 1"""),
            {"company": company, "name": values["name"], "id": str(target) if target else None}).first():
            raise HTTPException(409, "This name already exists.")
    elif action == "reorder_reminder":
        if values["variant_id"]:
            inventory._variant(str(target), values["variant_id"])
        current = record(db, company, "product_variants" if values["variant_id"] else "products", values["variant_id"] or target)
        result.update(reminder_before=current["reorder_reminder_date"], stock_change="0", creates_order=False)
    elif action == "stock_transfer_reverse":
        original = inventory.transfer_detail(str(target))
        if original["reversal_of_transfer_id"] or original["reversed_by_transfer_id"]:
            raise HTTPException(422, "This transfer is a reversal or has already been reversed.")
        changes = {}
        for line in original["lines"]:
            for store, sign in ((original["from_store_id"], 1), (original["to_store_id"], -1)):
                key = (str(store), str(line["product_id"]), str(line["variant_id"]) if line.get("variant_id") else None)
                changes[key] = changes.get(key, Decimal("0")) + Decimal(str(line["quantity"])) * sign
        result.update(transfer_date=date.today().isoformat(), stock_changes=stock_preview(db, company, changes))
    elif action == "movement_attribute":
        movement = record(db, company, "stock_movements", target)
        if str(target) not in {str(row["id"]) for row in inventory.missing_movement_sources(movement_id=str(target))["items"]}:
            raise HTTPException(422, "Only movements whose source document is missing can be re-attributed.")
        result.update(previous_reference_type=movement["reference_type"], previous_reference_id=str(movement["reference_id"]),
                      product_id=str(movement["product_id"]), quantity=str(movement["quantity"]), stock_change="0")
    else:
        raise ValueError(f"No Operations preview for {action}")
    if ACTIONS[action].high_impact:
        result["confirm_text"] = f"CONFIRM {action.upper()} {target}"
    return result


def apply(db, company, action, target, values):
    accounts, collections, inventory = AccountsService(db), CollectionsService(db), InventoryService(db, company)
    if action == "account_create":
        return accounts.create_account(company, AccountCreate.model_validate(values), commit=False)
    if action == "account_update":
        return accounts.update_account(target, company, AccountUpdate.model_validate(values), commit=False)
    if action == "account_transaction_create":
        return accounts.create_transaction(company, AccountTransactionCreate.model_validate(values), commit=False)
    if action == "account_transaction_reverse":
        result = accounts.reverse_transaction(target, company, TransactionReverseCreate.model_validate(values), commit=False)
        return {"id": result["reversal_transaction"]["id"], "reversal_of_transaction_id": target}
    if action == "borrowing_create":
        return SettlementsService(db).create_borrowing(company, BorrowingEntryCreate.model_validate(values), commit=False)
    if action == "refund_settle":
        return RefundSettlementsService(db).settle(target, RefundSettle.model_validate(values), commit=False)
    if action == "receivable_create":
        return collections.create_receivable(company, ReceivableCreate.model_validate(values), commit=False)
    if action == "receivable_status":
        return collections.update_receivable_status(target, company, ReceivableStatusUpdate.model_validate(values), commit=False)
    if action == "receivable_reminder":
        return collections.mark_reminder(target, company, ReceivableReminderUpdate.model_validate({**values, "reminded_by": "AI approved by Operations user"}), commit=False)
    if action == "purchase_receive":
        return PurchasesService(db).confirm_purchase_receipt(target, company, PurchaseReceiptConfirm.model_validate(values), commit=False)
    if action == "product_confirm":
        return inventory.confirm_draft(target, commit=False)
    if action == "product_merge":
        return inventory.merge_draft(target, ProductMerge.model_validate(values), commit=False)
    if action in {"variant_create", "variant_update", "offer_create", "offer_update"}:
        fields = {key: value for key, value in values.items() if key != "product_id"}
        if action.startswith("variant_"):
            result = inventory.save_variant(values["product_id"], VariantInput.model_validate(fields), target, commit=False)
            return {"id": result["saved_variant_id"], "product_id": values["product_id"]}
        result = inventory.save_offer(values["product_id"], VendorOfferInput.model_validate(fields), target, commit=False)
        return {"id": result["saved_offer_id"], "product_id": values["product_id"]}
    if action == "vendor_bulk_map":
        return inventory.bulk_map(BulkVendorMapping.model_validate(values), commit=False)
    if action in {"brand_create", "brand_update", "category_create", "category_update"}:
        kind = "brands" if action.startswith("brand_") else "categories"
        if target:
            return inventory.update_lookup(kind, target, ACTIONS[action].schema.model_validate(values), commit=False)
        return inventory.create_lookup(kind, **values, commit=False)
    if action == "reorder_reminder":
        inventory.remind(target, ReorderReminder.model_validate(values), commit=False)
        return {"id": values["variant_id"] or target}
    if action == "stock_transfer_reverse":
        return inventory.reverse_transfer(target, values["notes"], commit=False)
    if action == "movement_attribute":
        return inventory.attribute_external_source(target, ExternalMovementSource.model_validate(values), commit=False)
    raise ValueError(f"No Operations execution adapter for {action}")
