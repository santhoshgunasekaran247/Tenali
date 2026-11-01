from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


def purchase_payment_totals(db: Session, company_id: str, purchase: dict) -> tuple[Decimal, Decimal]:
    totals = db.execute(
        text(
            """
            select coalesce(sum(amount) filter (where reversed_at is null), 0) as active,
                   coalesce(sum(amount), 0) as recorded
            from purchase_payments where purchase_id = :id and company_id = :company
            """
        ),
        {"id": purchase["id"], "company": company_id},
    ).mappings().one()
    active, recorded = Decimal(totals["active"]), Decimal(totals["recorded"])
    if Decimal(purchase["amount_paid"]) > recorded:
        raise HTTPException(
            409, "Stored purchase payments exceed the recorded payment history; investigate the legacy data first"
        )
    return active, recorded


def sync_purchase_payments(db: Session, company_id: str, purchase_id: str) -> None:
    purchase = db.execute(
        text(
            """
            select id, total, amount_paid from purchases
            where id = :id and company_id = :company for update
            """
        ),
        {"id": purchase_id, "company": company_id},
    ).mappings().first()
    if not purchase:
        raise HTTPException(404, "Purchase not found")
    amount_paid, _ = purchase_payment_totals(db, company_id, dict(purchase))
    total = Decimal(purchase["total"])
    status = "PAID" if amount_paid >= total else "PARTIAL" if amount_paid > 0 else "UNPAID"
    db.execute(
        text(
            """
            update purchases set amount_paid = :amount, payment_status = :status
            where id = :id and company_id = :company
            """
        ),
        {"amount": amount_paid, "status": status, "id": purchase_id, "company": company_id},
    )
