from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


ACTIVE_BORROWING = """
not exists (
    select 1
    from account_transactions original
    join account_transactions reversal
      on reversal.company_id = original.company_id
     and reversal.reversal_of_transaction_id = original.id
    where original.company_id = b.company_id
      and (
        original.id = b.source_transaction_id
        or (b.source_transaction_id is null
            and original.source_type = 'borrowing' and original.source_id = b.id)
      )
)
"""


def lock_borrowing_party(db: Session, company_id: str, party_id: str) -> dict:
    party = db.execute(
        text(
            "select id, legal_name from parties where id = :id and company_id = :company for update"
        ),
        {"id": party_id, "company": company_id},
    ).mappings().first()
    if not party:
        raise HTTPException(404, "Party not found")
    return dict(party)


def available_repayment(db: Session, company_id: str, party_id: str, effective_date: date) -> Decimal:
    rows = db.execute(
        text(
            """
            with events as (
                select b.transaction_date,
                       case when b.direction = 'borrow' then b.amount else -b.amount end as amount
                from borrowings b
                where b.company_id = :company and b.party_id = :party
                union all
                select reversal.transaction_date,
                       case when b.direction = 'borrow' then -b.amount else b.amount end
                from borrowings b
                join account_transactions original
                  on original.company_id = b.company_id
                 and (original.id = b.source_transaction_id
                      or (b.source_transaction_id is null
                          and original.source_type = 'borrowing' and original.source_id = b.id))
                join account_transactions reversal
                  on reversal.company_id = original.company_id
                 and reversal.reversal_of_transaction_id = original.id
                where b.company_id = :company and b.party_id = :party
            ),
            changes as (
                select transaction_date, sum(amount) as amount
                from events group by transaction_date
            ),
            balances as (
                select transaction_date,
                       sum(amount) over (order by transaction_date) as balance
                from changes
            )
            select coalesce((select balance from balances where transaction_date <= :date
                             order by transaction_date desc limit 1), 0) as on_date,
                   (select min(balance) from balances where transaction_date > :date) as future_minimum
            """
        ),
        {"company": company_id, "party": party_id, "date": effective_date},
    ).mappings().one()
    available = Decimal(rows["on_date"])
    if rows["future_minimum"] is not None:
        available = min(available, Decimal(rows["future_minimum"]))
    return available


def lock_transaction_borrowing(
    db: Session, company_id: str, transaction_id: str, source_type: str | None, source_id: str | None
) -> dict | None:
    borrowing = db.execute(
        text(
            """
            select id, party_id, direction, amount
            from borrowings
            where company_id = :company
              and (source_transaction_id = :transaction_id
                   or (source_transaction_id is null and cast(:source_type as text) = 'borrowing'
                       and id = cast(:source_id as uuid)))
            """
        ),
        {"company": company_id, "transaction_id": transaction_id,
         "source_type": source_type, "source_id": source_id},
    ).mappings().first()
    if not borrowing:
        return None
    lock_borrowing_party(db, company_id, str(borrowing["party_id"]))
    return dict(borrowing)
