"""Reviewed deletion of posted transactions.

A deletion is always two calls: ``preview`` lists every record that goes with the transaction, the stock and
account balances that change, children that need explicit consent (payments, settlements) and blockers. Its
``token`` is a fingerprint of that exact impact. ``delete`` rebuilds the plan under locks and refuses unless the
token, the typed confirmation and a reason all match, so anything posted in between forces a fresh review.

Rows are removed inside a recorded ``transaction_deletions`` batch; a database trigger archives each one in full
in ``deleted_records`` and rejects deletes made outside a batch. Issued sales invoices are never deleted one at a
time: they are cancelled (and reissued) to keep the GST invoice series intact.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.borrowing_ledger import available_repayment
from app.services.collection_ledger import lock_receivable, sync_invoice_without_receivable, sync_receivable
from app.services.period_lock_service import assert_period_open
from app.services.purchase_ledger import sync_purchase_payments

RESET_CONFIRMATION = "DELETE ALL TRANSACTIONS"
IN_TYPES = {"PURCHASE", "GIFT_IN", "ADJUSTMENT_IN", "TRANSFER_IN"}
TITLES = {
    "purchases": "Purchase bills", "purchase_items": "Purchase bill lines", "purchase_payments": "Vendor payments",
    "receivable_payments": "Customer receipts", "account_transactions": "Account transactions",
    "stock_movements": "Stock movements", "stock_transfers": "Stock transfers", "borrowings": "Borrowing records",
    "cod_settlements": "COD settlements", "cod_settlement_items": "COD settlement lines",
    "document_links": "Attachment links", "posting_requests": "Saved submission keys",
    "invoices": "Sales invoices", "invoice_items": "Sales invoice lines", "receivables": "Receivables",
    "receivable_reminders": "Receivable reminders", "shop_orders": "Online orders", "expenses": "Expenses",
    "refund_settlements": "Refund settlements",
    "salary_transactions": "Salary payments", "settlements": "Settlements", "invoice_reconcile_runs": "Reconciliation runs",
    "stock_balances": "Store stock balances",
}
# Children before parents; reversals are removed before the rows they reverse.
DELETE_ORDER = (
    "posting_requests", "document_links", "cod_settlement_items", "cod_settlements", "receivable_reminders",
    "receivable_payments", "purchase_payments", "borrowings", "shop_orders", "refund_settlements", "account_transactions",
    "stock_movements", "stock_transfers", "receivables", "invoice_items", "invoices", "purchase_items", "purchases",
    "expenses", "salary_transactions", "settlements", "invoice_reconcile_runs", "stock_balances",
)
SELF_REFERENCES = {"account_transactions": "reversal_of_transaction_id", "stock_transfers": "reversal_of_transfer_id"}
KINDS = ("purchase", "purchase_payment", "receivable_payment", "account_transaction", "stock_adjustment",
         "stock_transfer", "borrowing", "cod_settlement", "invoice", "shop_order", "all")


def _money(value) -> str:
    return f"{Decimal(value):,.2f}"


class Plan:
    def __init__(self, kind: str, root_id: str | None):
        self.kind, self.root_id = kind, root_id
        self.label = ""
        self.rows: dict[str, dict[str, str]] = defaultdict(dict)
        self.critical: dict[tuple[str, str], str] = {}
        self.blockers: list[str] = []
        self.warnings: list[str] = []
        self.stock: dict[tuple[str, str, str | None], Decimal] = defaultdict(Decimal)
        self.accounts: dict[str, Decimal] = defaultdict(Decimal)
        self.purchases_to_sync: set[str] = set()
        self.purchase_paid_removed: dict[str, Decimal] = defaultdict(Decimal)
        self.receivable_received_removed: dict[str, Decimal] = defaultdict(Decimal)
        self.invoice_received_removed: dict[str, Decimal] = defaultdict(Decimal)
        self.receivables_to_sync: set[str] = set()
        self.invoices_to_sync: set[str] = set()
        self.counts: dict[str, int] = {}

    def add(self, table: str, row_id, label: str, critical: str | None = None) -> bool:
        row_id = str(row_id)
        if row_id in self.rows[table]:
            return False
        self.rows[table][row_id] = label
        if critical:
            self.critical[(table, row_id)] = critical
        return True

    def has(self, table: str, row_id) -> bool:
        return str(row_id) in self.rows.get(table, {})

    def block(self, message: str) -> None:
        if message not in self.blockers:
            self.blockers.append(message)


class TransactionDeletionService:
    def __init__(self, db: Session, company_id: str):
        self.db = db
        self.company_id = company_id

    # ---------------------------------------------------------------- helpers
    def _require_admin(self) -> dict:
        identity = self.db.info.get("tenant_context") or {}
        if identity.get("role") not in {"owner", "admin"}:
            raise HTTPException(403, "Only owners and administrators can delete transactions")
        return identity

    def _one(self, sql: str, **params):
        row = self.db.execute(text(sql), {"company": self.company_id, **params}).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(row) for row in self.db.execute(text(sql), {"company": self.company_id, **params}).mappings().all()]

    def _period(self, plan: Plan, when, what: str) -> None:
        if when is None:
            return
        try:
            assert_period_open(self.db, self.company_id, when.date() if isinstance(when, datetime) else when, what)
        except HTTPException as error:
            plan.block(str(error.detail))

    # ------------------------------------------------------------- collectors
    def _transaction(self, plan: Plan, tx: dict, critical: str | None = None, via_parent: bool = False) -> None:
        label = " ".join(part for part in (tx.get("reference") or "", tx.get("description") or "") if part) or "Transaction"
        if not plan.add("account_transactions", tx["id"], f"{label} - {_money(tx['amount'])} on {tx['transaction_date']}", critical):
            return
        if tx["from_account_id"]:
            plan.accounts[str(tx["from_account_id"])] += Decimal(tx["amount"])
        if tx["to_account_id"]:
            plan.accounts[str(tx["to_account_id"])] -= Decimal(tx["amount"])
        self._period(plan, tx["transaction_date"], "Deleting an account transaction")
        for refund in self._all("""select id, status, amount from refund_settlements where company_id=:company
                and (original_transaction_id=:id or reversal_transaction_id=:id)""", id=str(tx["id"])):
            plan.add("refund_settlements", refund["id"], f"{refund['status'].title()} refund settlement - {_money(refund['amount'])}",
                     critical or "Refund settlement for this payment")
        for reversal in self._all("""select * from account_transactions
                where company_id=:company and reversal_of_transaction_id=:id""", id=str(tx["id"])):
            self._transaction(plan, reversal, critical, via_parent=True)
        if tx["reversal_of_transaction_id"] and not plan.has("account_transactions", tx["reversal_of_transaction_id"]):
            original = self._one("select * from account_transactions where id=:id and company_id=:company", id=str(tx["reversal_of_transaction_id"]))
            for table in ("purchase_payments", "receivable_payments"):
                payment = self._one(f"select id from {table} where company_id=:company and reversed_by_transaction_id=:id", id=str(tx["id"]))
                if payment and not plan.has(table, payment["id"]):
                    plan.block("This is the reversal of a recorded payment. Delete the payment itself instead.")
            if original and not via_parent:
                plan.warnings.append("Deleting a reversal makes the original transaction count again in account balances.")
        order = self._one("select id from shop_orders where company_id=:company and advance_transaction_id=:id", id=str(tx["id"]))
        if order and not plan.has("shop_orders", order["id"]):
            plan.block("This is an online order payment. Cancel or refund the order from Online Orders instead.")
        if not via_parent:
            for borrowing in self._all("""select * from borrowings where company_id=:company and (source_transaction_id=:id
                    or (source_transaction_id is null and :source_type='borrowing' and id=cast(:source_id as uuid)))""",
                                       id=str(tx["id"]), source_type=tx["source_type"] or "", source_id=str(tx["source_id"]) if tx["source_id"] else None):
                self._borrowing(plan, borrowing, critical or "Borrowing recorded with this payment", from_transaction=True)

    def _borrowing(self, plan: Plan, borrowing: dict, critical: str | None = None, from_transaction: bool = False) -> None:
        if not plan.add("borrowings", borrowing["id"], f"{borrowing['direction'].title()} {_money(borrowing['amount'])} on {borrowing['transaction_date']}", critical):
            return
        reversed_already = self._one("""select 1 as found from account_transactions original join account_transactions reversal
                on reversal.company_id=original.company_id and reversal.reversal_of_transaction_id=original.id
            where original.company_id=:company and (original.id=cast(:source as uuid) or (original.source_type='borrowing' and original.source_id=:id))""",
                                     source=str(borrowing["source_transaction_id"]) if borrowing["source_transaction_id"] else None, id=str(borrowing["id"]))
        if borrowing["direction"] == "borrow" and not reversed_already:
            available = available_repayment(self.db, self.company_id, str(borrowing["party_id"]), borrowing["transaction_date"])
            if Decimal(borrowing["amount"]) > available:
                plan.block("Repayments to this party already use this borrowing. Delete those repayments first.")
        if not from_transaction:
            for tx in self._all("""select * from account_transactions where company_id=:company and reversal_of_transaction_id is null
                    and (id=cast(:source as uuid) or (source_type='borrowing' and source_id=:id))""",
                                source=str(borrowing["source_transaction_id"]) if borrowing["source_transaction_id"] else None, id=str(borrowing["id"])):
                self._transaction(plan, tx, critical, via_parent=True)

    def _payment_transactions(self, plan: Plan, source_type: str, payment: dict, critical: str | None) -> None:
        for tx in self._all("""select * from account_transactions where company_id=:company and reversal_of_transaction_id is null
                and source_type=:type and source_id=:id""", type=source_type, id=str(payment["id"])):
            self._transaction(plan, tx, critical, via_parent=True)
        if payment.get("reversed_by_transaction_id"):
            tx = self._one("select * from account_transactions where id=:id and company_id=:company", id=str(payment["reversed_by_transaction_id"]))
            if tx:
                self._transaction(plan, tx, critical, via_parent=True)

    def _purchase_payment(self, plan: Plan, payment: dict, critical: str | None = None) -> None:
        if not plan.add("purchase_payments", payment["id"], f"Vendor payment {_money(payment['amount'])} on {payment['payment_date']}", critical):
            return
        self._period(plan, payment["payment_date"], "Deleting a vendor payment")
        self._payment_transactions(plan, "purchase_payment", payment, critical)
        plan.purchases_to_sync.add(str(payment["purchase_id"]))
        if not payment.get("reversed_at"):
            plan.purchase_paid_removed[str(payment["purchase_id"])] += Decimal(payment["amount"])

    def _receivable_payment(self, plan: Plan, payment: dict, critical: str | None = None, in_settlement: bool = False) -> None:
        if str(payment.get("idempotency_key") or "").startswith("cod:") and not in_settlement:
            plan.block("This receipt is part of a COD settlement. Delete the COD settlement instead.")
        if not plan.add("receivable_payments", payment["id"], f"Customer receipt {_money(payment['amount'])} on {payment['payment_date']}", critical):
            return
        self._period(plan, payment["payment_date"], "Deleting a customer receipt")
        self._payment_transactions(plan, "receivable_payment", payment, critical)
        plan.receivables_to_sync.add(str(payment["receivable_id"]))
        if not payment.get("reversed_at"):
            plan.receivable_received_removed[str(payment["receivable_id"])] += Decimal(payment["amount"])

    def _movements(self, plan: Plan, reference_types: tuple[str, ...], reference_id: str) -> None:
        for movement in self._all("""select m.*, p.name as product_name from stock_movements m join products p on p.id=m.product_id
                where m.company_id=:company and m.reference_type = any(:types) and m.reference_id=:id""",
                                  types=list(reference_types), id=reference_id):
            self._movement(plan, movement)

    def _movement(self, plan: Plan, movement: dict) -> None:
        if not plan.add("stock_movements", movement["id"], f"{movement['product_name']}: {movement['movement_type'].replace('_', ' ').lower()} {movement['quantity']}"):
            return
        sign = Decimal(1) if movement["movement_type"] in IN_TYPES else Decimal(-1)
        key = (str(movement["store_id"]), str(movement["product_id"]), str(movement["variant_id"]) if movement["variant_id"] else None)
        plan.stock[key] -= sign * Decimal(movement["quantity"])

    def _links(self, plan: Plan, entity_type: str, entity_id: str) -> None:
        for link in self._all("""select l.id, d.file_name from document_links l join documents d on d.id=l.document_id
                where d.company_id=:company and l.entity_type=:type and l.entity_id=:id""", type=entity_type, id=entity_id):
            plan.add("document_links", link["id"], f"Attachment link to {link['file_name']} (the file itself is kept)")

    # ------------------------------------------------------------ root kinds
    def _plan_purchase(self, plan: Plan, purchase_id: str, lock: bool) -> None:
        purchase = self._one(f"select * from purchases where id=:id and company_id=:company{' for update' if lock else ''}", id=purchase_id)
        if not purchase:
            raise HTTPException(404, "Purchase not found")
        plan.label = purchase["voucher_number"] or purchase["bill_number"] or f"Purchase {purchase_id[:8]}"
        plan.add("purchases", purchase_id, f"{plan.label} - {_money(purchase['total'])} on {purchase['purchase_date']}")
        self._period(plan, purchase["purchase_date"], "Deleting a purchase bill")
        for item in self._all("""select i.id, coalesce(p.name, 'Item') as name, i.quantity from purchase_items i
                left join products p on p.id=i.product_id where i.purchase_id=:id""", id=purchase_id):
            plan.add("purchase_items", item["id"], f"{item['name']} x {item['quantity']}")
        for payment in self._all("select * from purchase_payments where company_id=:company and purchase_id=:id order by payment_date", id=purchase_id):
            self._purchase_payment(plan, payment, critical="Money already paid to the vendor for this bill")
        plan.purchases_to_sync.discard(purchase_id)
        self._movements(plan, ("purchase_receipt", "purchase_cancellation"), purchase_id)
        self._links(plan, "purchase", purchase_id)
        if self._one("select 1 as found from products where company_id=:company and is_draft and exists(select 1 from jsonb_array_elements(cast(:lines as jsonb)) line where line->>'product_id'=products.id::text)",
                     lines=json.dumps(purchase["line_items"] or [])):
            plan.warnings.append("Draft products created from this bill stay in Product Inventory; confirm, merge or delete them separately.")

    def _plan_payment(self, plan: Plan, table: str, payment_id: str, lock: bool) -> None:
        payment = self._one(f"select * from {table} where id=:id and company_id=:company{' for update' if lock else ''}", id=payment_id)
        if not payment:
            raise HTTPException(404, "Payment not found")
        if table == "purchase_payments":
            parent = self._one("select coalesce(voucher_number, bill_number) as number from purchases where id=:id", id=str(payment["purchase_id"]))
            plan.label = f"Vendor payment {_money(payment['amount'])}" + (f" for {parent['number']}" if parent and parent["number"] else "")
            self._purchase_payment(plan, payment)
        else:
            parent = self._one("""select i.invoice_number as number from receivables r left join invoices i on i.id=r.invoice_id
                where r.id=:id""", id=str(payment["receivable_id"]))
            plan.label = f"Customer receipt {_money(payment['amount'])}" + (f" for {parent['number']}" if parent and parent["number"] else "")
            self._receivable_payment(plan, payment)

    def _plan_transaction(self, plan: Plan, tx_id: str, lock: bool) -> None:
        tx = self._one(f"select * from account_transactions where id=:id and company_id=:company{' for update' if lock else ''}", id=tx_id)
        if not tx:
            raise HTTPException(404, "Transaction not found")
        if tx["source_type"] in {"purchase_payment", "receivable_payment"} and tx["source_id"] and not tx["reversal_of_transaction_id"]:
            table = "purchase_payments" if tx["source_type"] == "purchase_payment" else "receivable_payments"
            if self._one(f"select id from {table} where id=:id and company_id=:company", id=str(tx["source_id"])):
                plan.kind = tx["source_type"]
                return self._plan_payment(plan, table, str(tx["source_id"]), lock)
        plan.label = tx["reference"] or f"Transaction {_money(tx['amount'])} on {tx['transaction_date']}"
        self._transaction(plan, tx)
        if tx["source_type"] == "invoice" and tx["source_id"]:
            plan.warnings.append("This receipt was recorded against a sales invoice; the invoice will show it as unpaid again.")
            plan.invoices_to_sync.add(str(tx["source_id"]))
            reversed_already = self._one("select 1 as found from account_transactions where company_id=:company and reversal_of_transaction_id=:id", id=tx_id)
            if not tx["reversal_of_transaction_id"] and not reversed_already and tx["to_account_id"] and not tx["from_account_id"]:
                plan.invoice_received_removed[str(tx["source_id"])] += Decimal(tx["amount"])
        if tx["category"] in {"business_purchase", "business_billing", "business_expense"}:
            self._links(plan, "business_payment", tx_id)

    def _plan_adjustment(self, plan: Plan, movement_id: str, lock: bool) -> None:
        movement = self._one(f"""select m.*, p.name as product_name from stock_movements m join products p on p.id=m.product_id
            where m.id=:id and m.company_id=:company{' for update of m' if lock else ''}""", id=movement_id)
        if not movement:
            raise HTTPException(404, "Stock movement not found")
        if movement["reference_type"] not in {"manual_inventory", "external_document"}:
            plan.block("This stock movement was posted by a bill, invoice, order or transfer. Delete or cancel that record instead.")
        plan.label = f"{movement['product_name']} {movement['movement_type'].replace('_', ' ').lower()} {movement['quantity']}"
        self._period(plan, movement["created_at"], "Deleting a stock adjustment")
        self._movement(plan, movement)

    def _plan_transfer(self, plan: Plan, transfer_id: str, lock: bool) -> None:
        transfer = self._one("""select t.*, a.code as source, b.code as target from stock_transfers t
            join stores a on a.id=t.from_store_id join stores b on b.id=t.to_store_id
            where t.id=:id and t.company_id=:company""", id=transfer_id)
        if not transfer:
            raise HTTPException(404, "Stock transfer not found")
        plan.label = f"Transfer {transfer['source']} to {transfer['target']} on {transfer['transfer_date']}"
        for row in [transfer, *self._all("""select t.*, a.code as source, b.code as target from stock_transfers t
                join stores a on a.id=t.from_store_id join stores b on b.id=t.to_store_id
                where t.company_id=:company and t.reversal_of_transfer_id=:id""", id=transfer_id)]:
            critical = "Reversal of this transfer" if row is not transfer else None
            plan.add("stock_transfers", row["id"], f"Transfer {row['source']} to {row['target']} on {row['transfer_date']}", critical)
            self._period(plan, row["transfer_date"], "Deleting a stock transfer")
            self._movements(plan, ("stock_transfer",), str(row["id"]))

    def _plan_borrowing(self, plan: Plan, borrowing_id: str, lock: bool) -> None:
        borrowing = self._one(f"select * from borrowings where id=:id and company_id=:company{' for update' if lock else ''}", id=borrowing_id)
        if not borrowing:
            raise HTTPException(404, "Borrowing not found")
        plan.label = f"{borrowing['direction'].title()} {_money(borrowing['amount'])} on {borrowing['transaction_date']}"
        self._period(plan, borrowing["transaction_date"], "Deleting a borrowing")
        self._borrowing(plan, borrowing)

    def _plan_cod(self, plan: Plan, settlement_id: str, lock: bool) -> None:
        settlement = self._one(f"select * from cod_settlements where id=:id and company_id=:company{' for update' if lock else ''}", id=settlement_id)
        if not settlement:
            raise HTTPException(404, "COD settlement not found")
        plan.label = f"{settlement['courier']} {settlement['settlement_reference']}"
        plan.add("cod_settlements", settlement_id, f"COD settlement {plan.label} - {_money(settlement['received_amount'])}")
        self._period(plan, settlement["settlement_date"], "Deleting a COD settlement")
        for item in self._all("select order_id, amount from cod_settlement_items where settlement_id=:id", id=settlement_id):
            plan.add("cod_settlement_items", f"{settlement_id}:{item['order_id']}", f"Order {str(item['order_id'])[:8]} - {_money(item['amount'])}")
        prefix = f"cod:{settlement['courier']}:{settlement['settlement_reference']}:"
        for payment in self._all("""select * from receivable_payments where company_id=:company and left(idempotency_key, :size)=:prefix""",
                                 size=len(prefix), prefix=prefix):
            self._receivable_payment(plan, payment, in_settlement=True)

    def _plan_reset(self, plan: Plan) -> None:
        plan.label = RESET_CONFIRMATION
        for table in DELETE_ORDER:
            if table in {"invoice_items", "purchase_items", "document_links"}:
                parent = {"invoice_items": "invoices i on i.id=x.invoice_id", "purchase_items": "purchases i on i.id=x.purchase_id",
                          "document_links": "documents i on i.id=x.document_id and x.entity_type in ('purchase','business_payment')"}[table]
                count = self.db.execute(text(f"select count(*) from {table} x join {parent} where i.company_id=:company"),
                                        {"company": self.company_id}).scalar_one()
            else:
                count = self.db.execute(text(f"select count(*) from {table} where company_id=:company"), {"company": self.company_id}).scalar_one()
            if count:
                plan.counts[table] = int(count)
        if self._one("select 1 as found from accounting_period_locks where company_id=:company and is_active"):
            plan.block("Some accounting periods are locked. Reopen them before erasing all transactions.")
        open_orders = self.db.execute(text("""select count(*) from shop_orders where company_id=:company
            and status not in ('cancelled','delivered','collected','declined','expired')"""), {"company": self.company_id}).scalar_one()
        if open_orders:
            plan.warnings.append(f"{open_orders} online order(s) are still open. Customers who paid online are not refunded by this.")
        plan.warnings.append("Products, customers, vendors, accounts and stores are kept. All stock becomes zero.")
        plan.warnings.append("Invoice and purchase numbers continue from the last number used; deleted numbers are not reused.")

    def _build(self, kind: str, record_id: str | None, lock: bool) -> Plan:
        if kind not in KINDS:
            raise HTTPException(422, "Unsupported transaction type")
        if kind != "all" and not record_id:
            raise HTTPException(422, "Choose the transaction to delete")
        plan = Plan(kind, record_id)
        if kind == "invoice":
            invoice = self._one("select invoice_number, status from invoices where id=:id and company_id=:company", id=record_id)
            if not invoice:
                raise HTTPException(404, "Invoice not found")
            plan.label = invoice["invoice_number"]
            plan.block("Issued tax invoices are not deleted. Cancel the invoice (and issue a corrected one if needed) so the GST invoice series stays complete.")
        elif kind == "shop_order":
            plan.label = f"Order {record_id[:8]}"
            plan.block("Online orders are cancelled or refunded from Online Orders, not deleted.")
        elif kind == "purchase":
            self._plan_purchase(plan, record_id, lock)
        elif kind in {"purchase_payment", "receivable_payment"}:
            self._plan_payment(plan, f"{kind}s", record_id, lock)
        elif kind == "account_transaction":
            self._plan_transaction(plan, record_id, lock)
        elif kind == "stock_adjustment":
            self._plan_adjustment(plan, record_id, lock)
        elif kind == "stock_transfer":
            self._plan_transfer(plan, record_id, lock)
        elif kind == "borrowing":
            self._plan_borrowing(plan, record_id, lock)
        elif kind == "cod_settlement":
            self._plan_cod(plan, record_id, lock)
        else:
            self._plan_reset(plan)
        if kind != "all":
            ids = [row_id for table in ("purchases", "purchase_payments", "receivable_payments", "account_transactions", "stock_transfers")
                   for row_id in plan.rows.get(table, {})]
            for row in self._all("""select response->>'id' as id, operation from posting_requests
                    where company_id=:company and response->>'id' = any(:ids)""", ids=ids) if ids else []:
                plan.add("posting_requests", row["id"], f"Saved submission key ({row['operation']}) so the same form cannot re-post it")
        return plan

    # ----------------------------------------------------------- presentation
    def _stock_changes(self, plan: Plan, lock: bool) -> list[dict]:
        changes = []
        for (store_id, product_id, variant_id), delta in sorted(plan.stock.items()):
            if not delta:
                continue
            if lock:
                self.db.execute(text("""select id from stock_balances where company_id=:company and store_id=:store and product_id=:product
                    and variant_id is not distinct from cast(:variant as uuid) for update"""),
                                {"company": self.company_id, "store": store_id, "product": product_id, "variant": variant_id})
            row = self._one("""select coalesce((select quantity from stock_balances b where b.company_id=:company and b.store_id=:store
                    and b.product_id=:product and b.variant_id is not distinct from cast(:variant as uuid)), 0) as quantity,
                    (select code from stores where id=:store) as store_code, (select name from products where id=:product) as product_name,
                    (select variant_name from product_variants where id=cast(:variant as uuid)) as variant_name""",
                            store=store_id, product=product_id, variant=variant_id)
            after = Decimal(row["quantity"]) + delta
            name = row["product_name"] + (f" ({row['variant_name']})" if row["variant_name"] else "")
            if after < 0:
                plan.block(f"{name} at {row['store_code']} would fall to {after}: that stock has already been sold or moved. Delete or cancel those records first.")
            changes.append({"store_id": store_id, "product_id": product_id, "variant_id": variant_id, "store_code": row["store_code"],
                            "product_name": name, "current": Decimal(row["quantity"]), "change": delta, "after": after})
        return changes

    def _account_changes(self, plan: Plan) -> list[dict]:
        changes = []
        for account_id, delta in sorted(plan.accounts.items()):
            if delta:
                name = self.db.execute(text("select nickname from accounts where id=:id"), {"id": account_id}).scalar_one_or_none()
                changes.append({"account_id": account_id, "account_name": name or "Account", "change": delta})
        return changes

    def _render(self, plan: Plan, cascade: bool, lock: bool = False) -> dict:
        stock = self._stock_changes(plan, lock) if plan.kind != "all" else []
        accounts = self._account_changes(plan) if plan.kind != "all" else []
        if plan.kind == "all":
            deletes = [{"table": table, "title": TITLES[table], "count": count, "items": []} for table, count in plan.counts.items()]
            if not plan.counts:
                plan.block("There are no transactions to delete.")
        else:
            deletes = [{"table": table, "title": TITLES[table], "count": len(rows),
                        "items": [{"id": row_id, "label": label, "critical": plan.critical.get((table, row_id))} for row_id, label in rows.items()]}
                       for table in DELETE_ORDER if (rows := plan.rows.get(table))]
        critical = [{"table": table, "title": TITLES[table], "id": row_id, "label": plan.rows[table][row_id], "reason": reason}
                    for (table, row_id), reason in plan.critical.items()]
        fingerprint = {"kind": plan.kind, "id": plan.root_id, "cascade": bool(cascade), "label": plan.label,
                       "rows": {table: sorted(rows) for table, rows in plan.rows.items() if rows}, "counts": plan.counts,
                       "stock": [[c["store_id"], c["product_id"], c["variant_id"], str(c["current"]), str(c["change"])] for c in stock],
                       "accounts": [[c["account_id"], str(c["change"])] for c in accounts], "blockers": plan.blockers}
        if plan.kind == "all":
            fingerprint["latest"] = str(self.db.execute(text("""select greatest(
                (select max(created_at) from account_transactions where company_id=:company),
                (select max(created_at) from invoices where company_id=:company),
                (select max(created_at) from purchases where company_id=:company),
                (select max(created_at) from stock_movements where company_id=:company))"""), {"company": self.company_id}).scalar_one())
        token = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, default=str).encode()).hexdigest()
        return jsonable_encoder({
            "kind": plan.kind, "id": plan.root_id, "label": plan.label, "confirm_text": plan.label, "cascade": bool(cascade),
            "deletes": deletes, "critical": critical, "stock_changes": stock, "account_changes": accounts,
            "blockers": plan.blockers, "warnings": plan.warnings, "token": token,
            "can_delete": not plan.blockers and (not critical or bool(cascade)),
        })

    # ------------------------------------------------------------------ API
    def preview(self, kind: str, record_id: str | None = None, cascade: bool = False) -> dict:
        self._require_admin()
        return self._render(self._build(kind, record_id, lock=False), cascade)

    def delete(self, kind: str, record_id: str | None, token: str, confirm_text: str, reason: str, cascade: bool = False,
               *, commit: bool = True) -> dict:
        identity = self._require_admin()
        self.db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"{self.company_id}:transaction-deletion"})
        plan = self._build(kind, record_id, lock=True)
        preview = self._render(plan, cascade, lock=True)
        if preview["token"] != token:
            raise HTTPException(409, "These records changed after you reviewed them. Review the deletion again.")
        if preview["blockers"]:
            raise HTTPException(422, preview["blockers"][0])
        if preview["critical"] and not cascade:
            raise HTTPException(409, "Delete the linked payments and settlements first, or choose to delete them together.")
        if (confirm_text or "").strip() != preview["confirm_text"]:
            raise HTTPException(422, f"Type {preview['confirm_text']} exactly to confirm")
        reason = (reason or "").strip()
        if not reason:
            raise HTTPException(422, "Give a reason for the deletion")
        summary = {key: preview[key] for key in ("deletes", "critical", "stock_changes", "account_changes", "warnings", "cascade")}
        summary["deleted_by_name"] = identity.get("display_name") or identity.get("email")
        batch = self.db.execute(text("""insert into transaction_deletions(company_id,kind,root_id,label,reason,summary,deleted_by)
                values(:company,:kind,cast(:root as uuid),:label,:reason,cast(:summary as jsonb),cast(:actor as uuid)) returning id"""),
                                {"company": self.company_id, "kind": plan.kind, "root": record_id, "label": plan.label, "reason": reason,
                                 "summary": json.dumps(summary), "actor": identity.get("user_id")}).scalar_one()
        self.db.execute(text("select set_config('app.deletion_batch', :batch, true)"), {"batch": str(batch)})
        try:
            if plan.kind == "all":
                self._erase_all()
            else:
                self._apply(plan, preview["stock_changes"])
        finally:
            self.db.execute(text("select set_config('app.deletion_batch', '', true)"))
        if commit:
            self.db.commit()
        return {"deletion_id": str(batch), "label": plan.label,
                "deleted": {row["table"]: row["count"] for row in preview["deletes"]}}

    def history(self) -> dict:
        self._require_admin()
        rows = self._all("""select id, kind, label, reason, deleted_at, summary->'deletes' as deletes,
                summary->>'deleted_by_name' as deleted_by
            from transaction_deletions where company_id=:company order by deleted_at desc limit 100""")
        return {"items": jsonable_encoder(rows)}

    # ------------------------------------------------------------- execution
    def _apply(self, plan: Plan, stock_changes: list[dict]) -> None:
        for change in stock_changes:
            self.db.execute(text("""update stock_balances set quantity=:after where company_id=:company and store_id=:store
                and product_id=:product and variant_id is not distinct from cast(:variant as uuid)"""),
                            {"company": self.company_id, "store": change["store_id"], "product": change["product_id"],
                             "variant": change["variant_id"], "after": change["after"]})
        for table in DELETE_ORDER:
            ids = list(plan.rows.get(table, {}))
            if not ids:
                continue
            if table == "posting_requests":
                self.db.execute(text("delete from posting_requests where company_id=:company and response->>'id' = any(:ids)"),
                                {"company": self.company_id, "ids": ids})
            elif table == "cod_settlement_items":
                self.db.execute(text("delete from cod_settlement_items where company_id=:company and settlement_id = any(cast(:ids as uuid[]))"),
                                {"company": self.company_id, "ids": sorted({row_id.split(":")[0] for row_id in ids})})
            elif table in SELF_REFERENCES:
                column = SELF_REFERENCES[table]
                for condition in (f"{column} is not null", f"{column} is null"):
                    self.db.execute(text(f"delete from {table} where company_id=:company and id = any(cast(:ids as uuid[])) and {condition}"),
                                    {"company": self.company_id, "ids": ids})
            elif table in {"purchase_items", "document_links"}:
                self.db.execute(text(f"delete from {table} where id = any(cast(:ids as uuid[]))"), {"ids": ids})
            else:
                self.db.execute(text(f"delete from {table} where company_id=:company and id = any(cast(:ids as uuid[]))"),
                                {"company": self.company_id, "ids": ids})
        for purchase_id in plan.purchases_to_sync - set(plan.rows.get("purchases", {})):
            self.db.execute(text("update purchases set amount_paid=greatest(amount_paid - :removed, 0) where id=:id and company_id=:company"),
                            {"removed": plan.purchase_paid_removed[purchase_id], "id": purchase_id, "company": self.company_id})
            sync_purchase_payments(self.db, self.company_id, purchase_id)
        pairs: dict[str | None, str | None] = {}
        for receivable_id in plan.receivables_to_sync:
            row = self._one("select invoice_id from receivables where id=:id and company_id=:company", id=receivable_id)
            pairs[receivable_id] = str(row["invoice_id"]) if row and row["invoice_id"] else None
        loose_invoices = []
        for invoice_id in plan.invoices_to_sync:
            row = self._one("select id from receivables where company_id=:company and invoice_id=:id", id=invoice_id)
            if row:
                pairs.setdefault(str(row["id"]), invoice_id)
            else:
                loose_invoices.append(invoice_id)
        for receivable_id, invoice_id in pairs.items():
            removed = plan.receivable_received_removed[receivable_id] + (plan.invoice_received_removed[invoice_id] if invoice_id else Decimal(0))
            self._reduce_received(receivable_id, invoice_id, removed)
            stored, invoice = lock_receivable(self.db, self.company_id, receivable_id)
            sync_receivable(self.db, self.company_id, stored, invoice)
        for invoice_id in loose_invoices:
            self._reduce_received(None, invoice_id, plan.invoice_received_removed[invoice_id])
            invoice = self._one("select * from invoices where id=:id and company_id=:company for update", id=invoice_id)
            if invoice:
                sync_invoice_without_receivable(self.db, self.company_id, invoice)

    def _reduce_received(self, receivable_id: str | None, invoice_id: str | None, removed: Decimal) -> None:
        # Stored totals must drop with the deleted receipts, or the ledger's legacy-data guard rejects the re-sync.
        if not removed:
            return
        for table, row_id in (("receivables", receivable_id), ("invoices", invoice_id)):
            if row_id:
                self.db.execute(text(f"update {table} set amount_received=greatest(amount_received - :removed, 0) where id=:id and company_id=:company"),
                                {"removed": removed, "id": row_id, "company": self.company_id})

    def _erase_all(self) -> None:
        company = {"company": self.company_id}
        self.db.execute(text("update enquiries set invoice_id=null where company_id=:company and invoice_id is not null"), company)
        self.db.execute(text("update shop_orders set invoice_id=null, advance_transaction_id=null where company_id=:company"), company)
        for table in DELETE_ORDER:
            if table == "document_links":
                self.db.execute(text("""delete from document_links l using documents d where d.id=l.document_id and d.company_id=:company
                    and l.entity_type in ('purchase','business_payment')"""), company)
            elif table in {"invoice_items", "purchase_items"}:
                parent, column = ("invoices", "invoice_id") if table == "invoice_items" else ("purchases", "purchase_id")
                self.db.execute(text(f"delete from {table} x using {parent} p where p.id=x.{column} and p.company_id=:company"), company)
            elif table in SELF_REFERENCES:
                column = SELF_REFERENCES[table]
                self.db.execute(text(f"delete from {table} where company_id=:company and {column} is not null"), company)
                self.db.execute(text(f"delete from {table} where company_id=:company"), company)
            else:
                self.db.execute(text(f"delete from {table} where company_id=:company"), company)
