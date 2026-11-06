"""Refunds owed after a paid invoice or purchase bill is cancelled.

Cancellation never deletes money records. Each active receipt (invoice) or vendor payment (purchase) is
reversed with a normal reversal transaction, and a PENDING refund settlement is opened for it. Confirming the
settlement records how the money actually moved: the account, mode, date and reference of the reversal are
corrected in place while it is still pending, and the settlement becomes SETTLED (final).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.accounts import TransactionReverseCreate
from app.services.access import is_super
from app.services.collection_ledger import lock_invoice_receivables, receipt_totals, sync_invoice_without_receivable, sync_receivable
from app.services.period_lock_service import assert_period_open
from app.services.purchase_ledger import purchase_payment_totals, sync_purchase_payments

DIRECTIONS = {"invoice": "PAY_CUSTOMER", "purchase": "RECEIVE_VENDOR"}


class RefundSettle(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    account_id: str = Field(min_length=1)
    settled_on: date | None = None
    payment_mode: str | None = Field(default=None, max_length=50)
    reference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


def _require_accounts_access(db: Session) -> None:
    identity = db.info.get("tenant_context")
    if identity and not is_super(identity) and identity.get("modules") is not None and "accounts" not in identity["modules"]:
        raise HTTPException(403, "Reversing payments needs the accounts module. Ask an owner or administrator to cancel this document.")


def _payment_transactions(db: Session, company_id: str, kind: str, document_id: str) -> list[dict]:
    """Active (not yet reversed) money-in/out transactions recorded against the document."""
    if kind == "invoice":
        sql = """
            select t.* from account_transactions t
            where t.company_id=:company and t.reversal_of_transaction_id is null
              and not exists (select 1 from account_transactions r where r.company_id=t.company_id and r.reversal_of_transaction_id=t.id)
              and ((t.source_type='invoice' and t.source_id=cast(:id as uuid) and t.from_account_id is null and t.to_account_id is not null)
                or (t.source_type='receivable_payment' and t.source_id in (
                    select p.id from receivable_payments p join receivables r on r.id=p.receivable_id
                    where p.company_id=:company and r.invoice_id=cast(:id as uuid) and p.reversed_at is null)))
            order by t.transaction_date, t.created_at"""
    else:
        sql = """
            select t.* from account_transactions t
            where t.company_id=:company and t.reversal_of_transaction_id is null
              and not exists (select 1 from account_transactions r where r.company_id=t.company_id and r.reversal_of_transaction_id=t.id)
              and ((t.source_type='purchase_payment' and t.source_id in (
                    select id from purchase_payments where company_id=:company and purchase_id=cast(:id as uuid) and reversed_at is null))
                or (t.source_type='purchase' and t.source_id=cast(:id as uuid) and t.from_account_id is not null and t.to_account_id is null))
            order by t.transaction_date, t.created_at"""
    return [dict(row) for row in db.execute(text(sql), {"company": company_id, "id": document_id}).mappings().all()]


def _paid(db: Session, company_id: str, kind: str, document_id: str) -> Decimal:
    if kind == "invoice":
        invoice, receivable = lock_invoice_receivables(db, company_id, document_id)
        return receipt_totals(db, company_id, receivable, invoice)[0]
    purchase = db.execute(text("select id, amount_paid from purchases where id=:id and company_id=:company"),
                          {"id": document_id, "company": company_id}).mappings().one()
    return purchase_payment_totals(db, company_id, dict(purchase))[0]


def reverse_document_payments(db: Session, company_id: str, kind: str, document: dict, reason: str, when: date) -> list[dict]:
    """Reverse every active payment on a document being cancelled and open a pending refund for each."""
    from app.services.accounts_service import AccountsService

    _require_accounts_access(db)
    document_id = str(document["id"])
    accounts = AccountsService(db)
    created = []
    number = document.get("invoice_number") if kind == "invoice" else (document.get("bill_number") or document.get("voucher_number"))
    for tx in _payment_transactions(db, company_id, kind, document_id):
        if when < tx["transaction_date"]:
            raise HTTPException(422, "Cancellation cannot precede a payment recorded on this document")
        result = accounts.reverse_transaction(str(tx["id"]), company_id, TransactionReverseCreate(
            transaction_date=when, reference=tx["reference"],
            notes=f"Refund pending - {'invoice' if kind == 'invoice' else 'bill'} {number or ''} cancelled: {reason}"[:1000]), commit=False)
        reversal = result["reversal_transaction"]
        created.append(dict(db.execute(text("""
            insert into refund_settlements(company_id, direction, document_type, document_id, document_number, party_id,
                original_transaction_id, reversal_transaction_id, amount, reason)
            values (:company, :direction, :kind, :document, :number, :party, :original, :reversal, :amount, :reason)
            returning id, amount"""), {
            "company": company_id, "direction": DIRECTIONS[kind], "kind": kind, "document": document_id, "number": number,
            "party": str(document["customer_party_id" if kind == "invoice" else "vendor_party_id"] or "") or None,
            "original": str(tx["id"]), "reversal": str(reversal["id"]), "amount": tx["amount"], "reason": reason,
        }).mappings().one()))
    # Business-category payments skip the generic source effects, so resync the document totals explicitly.
    if kind == "invoice":
        invoice, receivable = lock_invoice_receivables(db, company_id, document_id)
        if receivable:
            sync_receivable(db, company_id, receivable, invoice)
        else:
            sync_invoice_without_receivable(db, company_id, invoice)
    else:
        sync_purchase_payments(db, company_id, document_id)
    if _paid(db, company_id, kind, document_id):
        raise HTTPException(409, "Some payments on this document have no linked account transaction. Reverse them from Accounts first.")
    return created


class RefundSettlementsService:
    def __init__(self, db: Session):
        self.db = db
        self.company_id = str(db.info["tenant_context"]["company_id"])

    def list(self, status: str | None = None) -> dict:
        if status and status not in {"PENDING", "SETTLED"}:
            raise HTTPException(422, "Status must be PENDING or SETTLED")
        rows = self.db.execute(text("""
            select s.id, s.direction, s.document_type, s.document_id, s.document_number, s.amount, s.status, s.reason,
                   s.settled_on, s.payment_mode, s.reference, s.notes, s.settled_at, s.created_at,
                   s.party_id, coalesce(p.nickname, p.legal_name) as party_name,
                   o.transaction_date as paid_on, o.payment_mode as original_payment_mode,
                   coalesce(o.to_account_id, o.from_account_id) as original_account_id, oa.nickname as original_account_name,
                   coalesce(r.from_account_id, r.to_account_id) as account_id, ra.nickname as account_name,
                   r.transaction_date as reversal_date, r.payment_mode as reversal_payment_mode
            from refund_settlements s
            join account_transactions o on o.id=s.original_transaction_id
            join account_transactions r on r.id=s.reversal_transaction_id
            left join parties p on p.id=s.party_id
            left join accounts oa on oa.id=coalesce(o.to_account_id, o.from_account_id)
            left join accounts ra on ra.id=coalesce(r.from_account_id, r.to_account_id)
            where s.company_id=:company and (cast(:status as text) is null or s.status=:status)
            order by s.status, s.created_at desc limit 300"""), {"company": self.company_id, "status": status}).mappings().all()
        return {"items": jsonable_encoder([dict(row) for row in rows]), "summary": self.summary()}

    def summary(self) -> dict:
        row = self.db.execute(text("""
            select count(*) filter (where direction='PAY_CUSTOMER') as customer_count,
                   coalesce(sum(amount) filter (where direction='PAY_CUSTOMER'), 0) as customer_amount,
                   count(*) filter (where direction='RECEIVE_VENDOR') as vendor_count,
                   coalesce(sum(amount) filter (where direction='RECEIVE_VENDOR'), 0) as vendor_amount
            from refund_settlements where company_id=:company and status='PENDING'"""), {"company": self.company_id}).mappings().one()
        return jsonable_encoder(dict(row))

    def settle(self, settlement_id: str, payload: RefundSettle) -> dict:
        _require_accounts_access(self.db)
        settlement = self.db.execute(text("""select * from refund_settlements where id=cast(:id as uuid) and company_id=:company for update"""),
                                     {"id": settlement_id, "company": self.company_id}).mappings().first()
        if not settlement:
            raise HTTPException(404, "Refund settlement not found")
        if settlement["status"] != "PENDING":
            raise HTTPException(409, "This refund is already settled")
        reversal = self.db.execute(text("select * from account_transactions where id=:id and company_id=:company for update"),
                                   {"id": settlement["reversal_transaction_id"], "company": self.company_id}).mappings().one()
        original = self.db.execute(text("select transaction_date from account_transactions where id=:id and company_id=:company"),
                                   {"id": settlement["original_transaction_id"], "company": self.company_id}).mappings().one()
        account = self.db.execute(text("select id from accounts where id=cast(:id as uuid) and company_id=:company and is_active"),
                                  {"id": payload.account_id, "company": self.company_id}).scalar_one_or_none()
        if not account:
            raise HTTPException(404, "Account not found or inactive")
        settled_on = payload.settled_on or date.today()
        if settled_on < original["transaction_date"]:
            raise HTTPException(422, "The refund cannot be dated before the original payment")
        if settled_on > date.today():
            raise HTTPException(422, "The refund date cannot be in the future")
        assert_period_open(self.db, self.company_id, reversal["transaction_date"], "Settling a refund")
        assert_period_open(self.db, self.company_id, settled_on, "Settling a refund")
        column = "from_account_id" if settlement["direction"] == "PAY_CUSTOMER" else "to_account_id"
        mode = payload.payment_mode or reversal["payment_mode"]
        reference = payload.reference or reversal["reference"]
        self.db.execute(text(f"""update account_transactions set {column}=cast(:account as uuid), payment_mode=:mode, reference=:reference,
                transaction_date=:settled_on, description=:description where id=:id and company_id=:company"""), {
            "account": payload.account_id, "mode": mode, "reference": reference, "settled_on": settled_on, "id": reversal["id"],
            "company": self.company_id,
            "description": ((reversal["description"] or "").replace("Refund pending", "Refund settled", 1) or "Refund settled")[:1000],
        })
        identity = self.db.info.get("tenant_context") or {}
        row = self.db.execute(text("""update refund_settlements set status='SETTLED', settled_on=:settled_on, account_id=cast(:account as uuid),
                payment_mode=:mode, reference=:reference, notes=:notes, settled_by=cast(:actor as uuid), settled_at=now()
            where id=:id returning id, status"""), {
            "settled_on": settled_on, "account": payload.account_id, "mode": mode, "reference": reference, "notes": payload.notes,
            "actor": identity.get("user_id"), "id": settlement["id"]}).mappings().one()
        self.db.commit()
        return jsonable_encoder(dict(row))
