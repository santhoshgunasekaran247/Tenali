from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.services.runtime_schema import managed_schema


def ensure_period_locks_table(db: Session) -> None:
    if managed_schema(db): return
    db.execute(
        text(
            """
            create table if not exists accounting_period_locks (
                id uuid primary key default gen_random_uuid(),
                company_id uuid not null references companies(id),
                period_start date not null,
                period_end date not null,
                reason text,
                closed_by text,
                is_active boolean not null default true,
                created_at timestamptz not null default now(),
                reopened_at timestamptz,
                reopened_by text,
                reopen_reason text,
                check (period_start <= period_end)
            )
            """
        )
    )
    db.execute(
        text(
            """
            create index if not exists idx_period_locks_company_dates
            on accounting_period_locks(company_id, period_start, period_end)
            """
        )
    )
    db.execute(
        text(
            """
            create index if not exists idx_period_locks_active
            on accounting_period_locks(company_id, is_active)
            """
        )
    )


def assert_period_open(
    db: Session,
    company_id: str,
    transaction_date: date,
    action_label: str,
) -> None:
    ensure_period_locks_table(db)
    lock_row = db.execute(
        text(
            """
            select id, period_start, period_end
            from accounting_period_locks
            where company_id = :company_id
              and is_active = true
              and :transaction_date between period_start and period_end
            order by period_start desc
            limit 1
            """
        ),
        {
            "company_id": company_id,
            "transaction_date": transaction_date,
        },
    ).mappings().first()

    if not lock_row:
        return

    raise HTTPException(
        status_code=422,
        detail=(
            f"{action_label} is blocked. "
            f"Period {lock_row['period_start']} to {lock_row['period_end']} is closed."
        ),
    )
