from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_invoice_receivables(
    db: Session, company_id: str, invoice_id: str
) -> tuple[dict, dict | None]:
    invoice = db.execute(
        text(
            """
            select id, customer_party_id, invoice_date, total, status,
                   collection_status, amount_received, reminder_date, bad_debt_reason
            from invoices
            where id = :invoice_id and company_id = :company_id
            for update
            """
        ),
        {"invoice_id": invoice_id, "company_id": company_id},
    ).mappings().first()
    if not invoice:
        raise HTTPException(404, "Invoice not found")

    receivables = db.execute(
        text(
            """
            select id, invoice_id, party_id, amount_due, amount_received, status,
                   reminder_date, bad_debt_reason
            from receivables
            where invoice_id = :invoice_id and company_id = :company_id
            order by id
            for update
            """
        ),
        {"invoice_id": invoice_id, "company_id": company_id},
    ).mappings().all()
    if len(receivables) > 1:
        raise HTTPException(409, "Invoice has multiple receivables; resolve them before proceeding")
    receivable = dict(receivables[0]) if receivables else None
    invoice = dict(invoice)
    if receivable and (
        receivable["party_id"] != invoice["customer_party_id"]
        or receivable["amount_due"] != invoice["total"]
    ):
        raise HTTPException(409, "Invoice and receivable party or total do not match")
    return invoice, receivable


def lock_receivable(
    db: Session, company_id: str, receivable_id: str
) -> tuple[dict, dict | None]:
    link = db.execute(
        text("select invoice_id from receivables where id = :id and company_id = :company"),
        {"id": receivable_id, "company": company_id},
    ).mappings().first()
    if not link:
        raise HTTPException(404, "Receivable not found")
    if link["invoice_id"]:
        invoice, receivable = lock_invoice_receivables(db, company_id, str(link["invoice_id"]))
        if not receivable or str(receivable["id"]).lower() != receivable_id.lower():
            raise HTTPException(409, "Receivable changed while it was being locked")
        return receivable, invoice

    receivable = db.execute(
        text(
            """
            select id, invoice_id, party_id, amount_due, amount_received, status,
                   reminder_date, bad_debt_reason
            from receivables
            where id = :id and company_id = :company
            for update
            """
        ),
        {"id": receivable_id, "company": company_id},
    ).mappings().first()
    if not receivable:
        raise HTTPException(404, "Receivable not found")
    return dict(receivable), None


def receipt_totals(
    db: Session, company_id: str, receivable: dict | None, invoice: dict | None
) -> tuple[Decimal, Decimal]:
    totals = db.execute(
        text(
            """
            select coalesce(sum(amount) filter (where active), 0) as active,
                   coalesce(sum(amount), 0) as recorded
            from (
                select t.amount, not exists (
                    select 1 from account_transactions reversal
                    where reversal.company_id = t.company_id
                      and reversal.reversal_of_transaction_id = t.id
                ) as active
                from account_transactions t
                where t.company_id = :company_id
                  and t.source_type = 'invoice'
                  and t.source_id = cast(:invoice_id as uuid)
                  and t.from_account_id is null and t.to_account_id is not null
                union all
                select p.amount, p.reversed_at is null as active
                from receivable_payments p
                where p.company_id = :company_id
                  and p.receivable_id = cast(:receivable_id as uuid)
            ) receipts
            """
        ),
        {
            "company_id": company_id,
            "invoice_id": str(invoice["id"]) if invoice else None,
            "receivable_id": str(receivable["id"]) if receivable else None,
        },
    ).mappings().one()
    active, recorded = Decimal(totals["active"]), Decimal(totals["recorded"])
    stored = [Decimal(row["amount_received"]) for row in (receivable, invoice) if row]
    if stored and max(stored) > recorded:
        raise HTTPException(
            409,
            "Stored receipts exceed the recorded payment history; investigate the legacy data first",
        )
    return active, recorded


def payment_status(amount_due: Decimal, received: Decimal) -> str:
    if received <= 0:
        return "UNPAID"
    if received >= amount_due:
        return "SETTLED"
    return "PARTIAL"


def sync_receivable(
    db: Session, company_id: str, receivable: dict, invoice: dict | None
) -> tuple[Decimal, str, bool]:
    received, _ = receipt_totals(db, company_id, receivable, invoice)
    status = payment_status(Decimal(receivable["amount_due"]), received)
    if receivable["status"] == "BAD_DEBT" and status != "SETTLED":
        status = "BAD_DEBT"
    reason = receivable["bad_debt_reason"] if status == "BAD_DEBT" else None
    changed = False
    if (
        receivable["amount_received"] != received
        or receivable["status"] != status
        or receivable["bad_debt_reason"] != reason
    ):
        db.execute(
            text(
                """
                update receivables
                set amount_received = :received, status = :status,
                    bad_debt_reason = :reason, updated_at = now()
                where id = :id and company_id = :company
                """
            ),
            {"received": received, "status": status, "reason": reason,
             "id": receivable["id"], "company": company_id},
        )
        changed = True
    if invoice and (
        invoice["amount_received"] != received
        or invoice["collection_status"] != status
        or invoice["reminder_date"] != receivable["reminder_date"]
        or invoice["bad_debt_reason"] != reason
    ):
        db.execute(
            text(
                """
                update invoices
                set amount_received = :received, collection_status = :status,
                    reminder_date = :reminder_date, bad_debt_reason = :reason
                where id = :id and company_id = :company
                """
            ),
            {"received": received, "status": status, "reason": reason,
             "reminder_date": receivable["reminder_date"],
             "id": invoice["id"], "company": company_id},
        )
        changed = True
    return received, status, changed


def sync_invoice_without_receivable(db: Session, company_id: str, invoice: dict) -> None:
    received, _ = receipt_totals(db, company_id, None, invoice)
    status = payment_status(Decimal(invoice["total"]), received)
    if invoice["collection_status"] == "BAD_DEBT" and status != "SETTLED":
        status = "BAD_DEBT"
    db.execute(
        text(
            """
            update invoices
            set amount_received = :received, collection_status = :status,
                bad_debt_reason = case when :status = 'BAD_DEBT' then bad_debt_reason else null end
            where id = :id and company_id = :company
            """
        ),
        {"received": received, "status": status, "id": invoice["id"], "company": company_id},
    )
