from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from io import StringIO

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.collections import (
    ReceivableCreate,
    ReceivablePaymentCreate,
    ReceivableReminderUpdate,
    ReceivableStatusUpdate,
)
from app.services.period_lock_service import assert_period_open

ALLOWED_RECEIVABLE_STATUS = {"UNPAID", "PARTIAL", "SETTLED", "BAD_DEBT"}


class CollectionsService:
    def __init__(self, db: Session):
        self.db = db

    def _resolve_company_id(self, company_id: str | None) -> str:
        if company_id:
            return company_id

        first_company = self.db.execute(
            text("select id from companies where is_active = true order by created_at asc limit 1")
        ).scalar_one_or_none()
        if not first_company:
            raise HTTPException(status_code=404, detail="No company configured")
        return str(first_company)

    def _ensure_tables(self) -> None:
        self.db.execute(
            text(
                """
                create table if not exists receivables (
                    id uuid primary key default gen_random_uuid(),
                    company_id uuid not null references companies(id),
                    party_id uuid not null references parties(id),
                    invoice_id uuid references invoices(id),
                    reference text,
                    amount_due numeric(14,2) not null check (amount_due > 0),
                    amount_received numeric(14,2) not null default 0,
                    status text not null default 'UNPAID' check (status in ('UNPAID','PARTIAL','SETTLED','BAD_DEBT')),
                    due_date date,
                    reminder_date date,
                    last_reminded_at timestamptz,
                    bad_debt_reason text,
                    notes text,
                    created_by uuid references user_profiles(id),
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
                """
            )
        )
        self.db.execute(
            text(
                """
                create table if not exists receivable_payments (
                    id uuid primary key default gen_random_uuid(),
                    receivable_id uuid not null references receivables(id) on delete cascade,
                    company_id uuid not null references companies(id),
                    account_id uuid references accounts(id),
                    amount numeric(14,2) not null check (amount > 0),
                    payment_mode text not null,
                    idempotency_key text,
                    reference text,
                    payment_date date not null default current_date,
                    notes text,
                    reversed_at timestamptz,
                    reversed_by_transaction_id uuid references account_transactions(id),
                    created_by uuid references user_profiles(id),
                    created_at timestamptz not null default now()
                )
                """
            )
        )
        self.db.execute(text("alter table receivable_payments add column if not exists idempotency_key text"))
        self.db.execute(text("alter table receivable_payments add column if not exists reversed_at timestamptz"))
        self.db.execute(
            text(
                """
                alter table receivable_payments
                add column if not exists reversed_by_transaction_id uuid references account_transactions(id)
                """
            )
        )
        self.db.execute(
            text(
                "create index if not exists idx_receivables_company_status_due on receivables(company_id, status, due_date)"
            )
        )
        self.db.execute(text("create index if not exists idx_receivables_party on receivables(party_id)"))
        self.db.execute(
            text(
                "create index if not exists idx_receivable_payments_receivable on receivable_payments(receivable_id)"
            )
        )
        self.db.execute(
            text(
                """
                create unique index if not exists uq_receivable_payments_idempotency
                on receivable_payments(company_id, idempotency_key)
                where idempotency_key is not null
                """
            )
        )
        self.db.execute(
            text(
                """
                create table if not exists receivable_reminders (
                    id uuid primary key default gen_random_uuid(),
                    receivable_id uuid not null references receivables(id) on delete cascade,
                    company_id uuid not null references companies(id),
                    reminder_date date,
                    next_reminder_date date,
                    reminded_at timestamptz not null default now(),
                    reminded_by text,
                    notes text
                )
                """
            )
        )
        self.db.execute(
            text(
                "create index if not exists idx_receivable_reminders_receivable on receivable_reminders(receivable_id, reminded_at desc)"
            )
        )

    def create_receivable(self, company_id: str | None, payload: ReceivableCreate) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        if payload.amount_due <= 0:
            raise HTTPException(status_code=422, detail="amount_due must be greater than zero")

        party = self.db.execute(
            text(
                """
                select id, legal_name
                from parties
                where id = :party_id and company_id = :company_id
                """
            ),
            {"party_id": str(payload.party_id), "company_id": resolved_company_id},
        ).mappings().first()
        if not party:
            raise HTTPException(status_code=404, detail="Party not found")

        row = self.db.execute(
            text(
                """
                insert into receivables (
                    company_id,
                    party_id,
                    invoice_id,
                    reference,
                    amount_due,
                    due_date,
                    reminder_date,
                    notes
                ) values (
                    :company_id,
                    :party_id,
                    :invoice_id,
                    :reference,
                    :amount_due,
                    :due_date,
                    :reminder_date,
                    :notes
                )
                returning
                    id,
                    company_id,
                    party_id,
                    invoice_id,
                    reference,
                    amount_due,
                    amount_received,
                    status,
                    due_date,
                    reminder_date,
                    bad_debt_reason,
                    notes,
                    created_at
                """
            ),
            {
                "company_id": resolved_company_id,
                "party_id": str(payload.party_id),
                "invoice_id": str(payload.invoice_id) if payload.invoice_id else None,
                "reference": payload.reference,
                "amount_due": payload.amount_due,
                "due_date": payload.due_date,
                "reminder_date": payload.reminder_date,
                "notes": payload.notes,
            },
        ).mappings().first()
        self.db.commit()

        if not row:
            raise HTTPException(status_code=500, detail="Failed to create receivable")

        result = dict(row)
        result["party_name"] = party["legal_name"]
        result["balance_amount"] = float(result["amount_due"]) - float(result["amount_received"])
        return result

    def list_receivables(self, company_id: str | None, status: str | None = None) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        query = """
            select
                r.id,
                r.company_id,
                r.party_id,
                p.legal_name as party_name,
                r.invoice_id,
                r.reference,
                r.amount_due,
                r.amount_received,
                (r.amount_due - r.amount_received) as balance_amount,
                r.status,
                r.due_date,
                r.reminder_date,
                r.bad_debt_reason,
                r.notes,
                r.created_at
            from receivables r
            join parties p on p.id = r.party_id
            where r.company_id = :company_id
        """
        params: dict[str, object] = {"company_id": resolved_company_id}
        if status:
            normalized = status.strip().upper()
            if normalized not in ALLOWED_RECEIVABLE_STATUS:
                raise HTTPException(status_code=422, detail="Invalid status filter")
            query += " and r.status = :status"
            params["status"] = normalized

        query += " order by coalesce(r.reminder_date, r.due_date, r.created_at::date) asc, r.created_at desc"
        rows = self.db.execute(text(query), params).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def export_ar_aging_csv(self, company_id: str | None, as_of: str | None = None) -> str:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        try:
            as_of_value = date.fromisoformat(as_of) if as_of else date.today()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="as_of must be YYYY-MM-DD") from exc

        rows = self.db.execute(
            text(
                """
                select
                    r.id,
                    p.legal_name as party_name,
                    r.reference,
                    r.invoice_id,
                    r.due_date,
                    r.created_at::date as created_date,
                    r.amount_due,
                    r.amount_received,
                    (r.amount_due - r.amount_received) as balance_amount,
                    r.status
                from receivables r
                join parties p on p.id = r.party_id
                where r.company_id = :company_id
                  and r.status in ('UNPAID', 'PARTIAL')
                  and (r.amount_due - r.amount_received) > 0
                order by coalesce(r.due_date, r.created_at::date) asc, r.created_at asc
                """
            ),
            {"company_id": resolved_company_id},
        ).mappings().all()

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "party_name",
                "reference",
                "invoice_id",
                "due_date",
                "balance_amount",
                "age_days",
                "bucket",
                "status",
            ]
        )

        for row in rows:
            due_base = row["due_date"] or row["created_date"]
            age_days = max((as_of_value - due_base).days, 0)
            if age_days <= 30:
                bucket = "0-30"
            elif age_days <= 60:
                bucket = "31-60"
            elif age_days <= 90:
                bucket = "61-90"
            elif age_days <= 180:
                bucket = "91-180"
            else:
                bucket = "180+"

            writer.writerow(
                [
                    row["party_name"],
                    row["reference"] or "",
                    row["invoice_id"] or "",
                    row["due_date"] or "",
                    row["balance_amount"],
                    age_days,
                    bucket,
                    row["status"],
                ]
            )
        return output.getvalue()

    def collect_receivable(
        self, receivable_id: str, company_id: str | None, payload: ReceivablePaymentCreate
    ) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        if payload.amount <= 0:
            raise HTTPException(status_code=422, detail="amount must be greater than zero")
        if not payload.payment_mode.strip():
            raise HTTPException(status_code=422, detail="payment_mode is required")
        if not payload.account_id:
            raise HTTPException(status_code=422, detail="account_id is required for collection payments")

        receivable = self.db.execute(
            text(
                """
                select id, amount_due, amount_received, status
                from receivables
                where id = :receivable_id and company_id = :company_id
                """
            ),
            {"receivable_id": receivable_id, "company_id": resolved_company_id},
        ).mappings().first()
        if not receivable:
            raise HTTPException(status_code=404, detail="Receivable not found")
        if receivable["status"] == "BAD_DEBT":
            raise HTTPException(status_code=422, detail="Cannot collect payment on bad debt")

        account_id = str(payload.account_id)
        account = self.db.execute(
            text(
                """
                select id
                from accounts
                where id = :account_id and company_id = :company_id and is_active = true
                """
            ),
            {"account_id": account_id, "company_id": resolved_company_id},
        ).scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=404, detail="Collection account not found")

        current_received = Decimal(str(receivable["amount_received"]))
        amount_due = Decimal(str(receivable["amount_due"]))
        new_received = current_received + Decimal(str(payload.amount))
        if new_received - amount_due > Decimal("0.0001"):
            raise HTTPException(status_code=422, detail="Collected amount exceeds due amount")

        existing = self.db.execute(
            text(
                """
                select id
                from receivable_payments
                where company_id = :company_id
                  and idempotency_key = :idempotency_key
                limit 1
                """
            ),
            {
                "company_id": resolved_company_id,
                "idempotency_key": payload.idempotency_key,
            },
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Duplicate collection submission detected")

        payment_date = payload.payment_date or date.today()
        assert_period_open(
            db=self.db,
            company_id=resolved_company_id,
            transaction_date=payment_date,
            action_label="Posting collection payment",
        )
        payment = self.db.execute(
            text(
                """
                insert into receivable_payments (
                    receivable_id,
                    company_id,
                    account_id,
                    amount,
                    payment_mode,
                    idempotency_key,
                    reference,
                    payment_date,
                    notes
                ) values (
                    :receivable_id,
                    :company_id,
                    :account_id,
                    :amount,
                    :payment_mode,
                    :idempotency_key,
                    :reference,
                    :payment_date,
                    :notes
                )
                returning id, receivable_id, company_id, account_id, amount, payment_mode, idempotency_key, reference, payment_date, notes, created_at
                """
            ),
            {
                "receivable_id": receivable_id,
                "company_id": resolved_company_id,
                "account_id": account_id,
                "amount": payload.amount,
                "payment_mode": payload.payment_mode.strip(),
                "idempotency_key": payload.idempotency_key,
                "reference": payload.reference,
                "payment_date": payment_date,
                "notes": payload.notes,
            },
        ).mappings().first()

        self._sync_receivable_payment_summary(receivable_id=receivable_id, company_id=resolved_company_id)

        self.db.execute(
            text(
                """
                insert into account_transactions (
                    company_id,
                    from_account_id,
                    to_account_id,
                    amount,
                    payment_mode,
                    reference,
                    category,
                    description,
                    transaction_date,
                    source_type,
                    source_id
                ) values (
                    :company_id,
                    null,
                    :to_account_id,
                    :amount,
                    :payment_mode,
                    :reference,
                    :category,
                    :description,
                    :transaction_date,
                    :source_type,
                    :source_id
                )
                """
            ),
            {
                "company_id": resolved_company_id,
                "to_account_id": account_id,
                "amount": payload.amount,
                "payment_mode": payload.payment_mode.strip(),
                "reference": payload.reference,
                "category": "sales_collection",
                "description": payload.notes or "Sales collection",
                "transaction_date": payment_date,
                "source_type": "receivable_payment",
                "source_id": str(payment["id"]) if payment else None,
            },
        )

        self._sync_invoice_from_receivable(
            receivable_id=receivable_id,
            company_id=resolved_company_id,
        )

        self.db.commit()
        if not payment:
            raise HTTPException(status_code=500, detail="Failed to create payment")
        return dict(payment)

    def update_receivable_status(
        self, receivable_id: str, company_id: str | None, payload: ReceivableStatusUpdate
    ) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        status = payload.status.strip().upper()
        if status not in ALLOWED_RECEIVABLE_STATUS:
            raise HTTPException(status_code=422, detail="Invalid status")

        row = self.db.execute(
            text(
                """
                update receivables
                set
                    status = :status,
                    bad_debt_reason = :bad_debt_reason,
                    reminder_date = :reminder_date,
                    updated_at = now()
                where id = :receivable_id and company_id = :company_id
                returning id
                """
            ),
            {
                "status": status,
                "bad_debt_reason": payload.bad_debt_reason if status == "BAD_DEBT" else None,
                "reminder_date": payload.reminder_date,
                "receivable_id": receivable_id,
                "company_id": resolved_company_id,
            },
        ).mappings().first()

        if not row:
            raise HTTPException(status_code=404, detail="Receivable not found")
        self._sync_invoice_from_receivable(
            receivable_id=receivable_id,
            company_id=resolved_company_id,
        )
        self.db.commit()
        return self._get_receivable(company_id=resolved_company_id, receivable_id=receivable_id)

    def list_due_reminders(self, company_id: str | None, as_of: date | None = None) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)
        reference_date = as_of or date.today()

        rows = self.db.execute(
            text(
                """
                select
                    r.id,
                    r.company_id,
                    r.party_id,
                    p.legal_name as party_name,
                    r.invoice_id,
                    r.reference,
                    r.amount_due,
                    r.amount_received,
                    (r.amount_due - r.amount_received) as balance_amount,
                    r.status,
                    r.due_date,
                    r.reminder_date,
                    r.bad_debt_reason,
                    r.notes,
                    r.created_at
                from receivables r
                join parties p on p.id = r.party_id
                where r.company_id = :company_id
                  and r.status in ('UNPAID','PARTIAL')
                  and coalesce(r.reminder_date, r.due_date) <= :as_of
                order by coalesce(r.reminder_date, r.due_date) asc, r.created_at asc
                """
            ),
            {"company_id": resolved_company_id, "as_of": reference_date},
        ).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def mark_reminder(
        self, receivable_id: str, company_id: str | None, payload: ReceivableReminderUpdate
    ) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        current = self.db.execute(
            text(
                """
                select reminder_date
                from receivables
                where id = :receivable_id
                  and company_id = :company_id
                  and status in ('UNPAID','PARTIAL')
                """
            ),
            {
                "receivable_id": receivable_id,
                "company_id": resolved_company_id,
            },
        ).mappings().first()
        if not current:
            raise HTTPException(status_code=404, detail="Receivable not found or not collectible")

        row = self.db.execute(
            text(
                """
                update receivables
                set
                    last_reminded_at = now(),
                    reminder_date = :next_reminder_date,
                    notes = case
                        when :notes is null or :notes = '' then notes
                        when notes is null or notes = '' then :notes
                        else notes || E'\\n' || :notes
                    end,
                    updated_at = now()
                where id = :receivable_id
                  and company_id = :company_id
                  and status in ('UNPAID','PARTIAL')
                returning id
                """
            ),
            {
                "next_reminder_date": payload.next_reminder_date,
                "notes": payload.notes,
                "receivable_id": receivable_id,
                "company_id": resolved_company_id,
            },
        ).mappings().first()

        self.db.execute(
            text(
                """
                insert into receivable_reminders (
                    receivable_id,
                    company_id,
                    reminder_date,
                    next_reminder_date,
                    reminded_by,
                    notes
                ) values (
                    :receivable_id,
                    :company_id,
                    :reminder_date,
                    :next_reminder_date,
                    :reminded_by,
                    :notes
                )
                """
            ),
            {
                "receivable_id": receivable_id,
                "company_id": resolved_company_id,
                "reminder_date": current["reminder_date"],
                "next_reminder_date": payload.next_reminder_date,
                "reminded_by": payload.reminded_by or "operations_user",
                "notes": payload.notes,
            },
        )
        self._sync_invoice_from_receivable(
            receivable_id=receivable_id,
            company_id=resolved_company_id,
        )
        self.db.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Receivable not found or not collectible")
        return self._get_receivable(company_id=resolved_company_id, receivable_id=receivable_id)

    def list_reminder_history(
        self,
        receivable_id: str,
        company_id: str | None,
        from_date: date | None = None,
        to_date: date | None = None,
        reminded_by: str | None = None,
    ) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        if from_date and to_date and from_date > to_date:
            raise HTTPException(status_code=422, detail="from_date cannot be after to_date")

        receivable_exists = self.db.execute(
            text(
                """
                select id
                from receivables
                where id = :receivable_id and company_id = :company_id
                """
            ),
            {
                "receivable_id": receivable_id,
                "company_id": resolved_company_id,
            },
        ).scalar_one_or_none()
        if not receivable_exists:
            raise HTTPException(status_code=404, detail="Receivable not found")

        query = """
            select
                id,
                receivable_id,
                company_id,
                reminder_date,
                next_reminder_date,
                reminded_at,
                reminded_by,
                notes
            from receivable_reminders
            where receivable_id = :receivable_id
              and company_id = :company_id
        """
        params: dict[str, object] = {
            "receivable_id": receivable_id,
            "company_id": resolved_company_id,
        }

        if from_date:
            query += " and reminded_at::date >= :from_date"
            params["from_date"] = from_date
        if to_date:
            query += " and reminded_at::date <= :to_date"
            params["to_date"] = to_date
        if reminded_by and reminded_by.strip():
            query += " and coalesce(reminded_by, '') ilike :reminded_by"
            params["reminded_by"] = f"%{reminded_by.strip()}%"

        query += " order by reminded_at desc"
        rows = self.db.execute(text(query), params).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def _sync_invoice_from_receivable(self, receivable_id: str, company_id: str) -> None:
        receivable = self.db.execute(
            text(
                """
                select invoice_id, amount_received, status, reminder_date, bad_debt_reason
                from receivables
                where id = :receivable_id and company_id = :company_id
                """
            ),
            {
                "receivable_id": receivable_id,
                "company_id": company_id,
            },
        ).mappings().first()

        if not receivable or not receivable["invoice_id"]:
            return

        self.db.execute(
            text(
                """
                update invoices
                set
                    collection_status = :collection_status,
                    amount_received = :amount_received,
                    reminder_date = :reminder_date,
                    bad_debt_reason = :bad_debt_reason
                where id = :invoice_id and company_id = :company_id
                """
            ),
            {
                "invoice_id": str(receivable["invoice_id"]),
                "company_id": company_id,
                "collection_status": receivable["status"],
                "amount_received": receivable["amount_received"],
                "reminder_date": receivable["reminder_date"],
                "bad_debt_reason": (
                    receivable["bad_debt_reason"] if receivable["status"] == "BAD_DEBT" else None
                ),
            },
        )

    def _sync_receivable_payment_summary(self, receivable_id: str, company_id: str) -> None:
        receivable = self.db.execute(
            text(
                """
                select id, amount_due
                from receivables
                where id = :receivable_id and company_id = :company_id
                """
            ),
            {
                "receivable_id": receivable_id,
                "company_id": company_id,
            },
        ).mappings().first()
        if not receivable:
            raise HTTPException(status_code=404, detail="Receivable not found")

        amount_due = Decimal(str(receivable["amount_due"]))
        total_received = Decimal(
            str(
                self.db.execute(
                    text(
                        """
                        select coalesce(sum(amount), 0)
                        from receivable_payments
                        where receivable_id = :receivable_id
                          and company_id = :company_id
                          and reversed_at is null
                        """
                    ),
                    {
                        "receivable_id": receivable_id,
                        "company_id": company_id,
                    },
                ).scalar_one()
                or 0
            )
        )

        if total_received <= Decimal("0"):
            status = "UNPAID"
        elif amount_due - total_received <= Decimal("0.0001"):
            status = "SETTLED"
        else:
            status = "PARTIAL"

        self.db.execute(
            text(
                """
                update receivables
                set
                    amount_received = :amount_received,
                    status = :status,
                    updated_at = now()
                where id = :receivable_id and company_id = :company_id
                """
            ),
            {
                "amount_received": total_received,
                "status": status,
                "receivable_id": receivable_id,
                "company_id": company_id,
            },
        )

    def _get_receivable(self, company_id: str, receivable_id: str) -> dict:
        row = self.db.execute(
            text(
                """
                select
                    r.id,
                    r.company_id,
                    r.party_id,
                    p.legal_name as party_name,
                    r.invoice_id,
                    r.reference,
                    r.amount_due,
                    r.amount_received,
                    (r.amount_due - r.amount_received) as balance_amount,
                    r.status,
                    r.due_date,
                    r.reminder_date,
                    r.bad_debt_reason,
                    r.notes,
                    r.created_at
                from receivables r
                join parties p on p.id = r.party_id
                where r.id = :receivable_id and r.company_id = :company_id
                """
            ),
            {"receivable_id": receivable_id, "company_id": company_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Receivable not found")
        return dict(row)
