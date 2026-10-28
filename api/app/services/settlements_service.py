from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.services.runtime_schema import managed_schema

from app.schemas.settlements import BorrowingEntryCreate
from app.services.period_lock_service import assert_period_open

ALLOWED_DIRECTIONS = {"borrow", "repay"}


class SettlementsService:
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

    def _ensure_table(self) -> None:
        if managed_schema(self.db): return
        # Keeps environments operable while migrations are being formalized.
        self.db.execute(
            text(
                """
                create table if not exists borrowings (
                    id uuid primary key default gen_random_uuid(),
                    company_id uuid not null references companies(id),
                    party_id uuid not null references parties(id),
                    direction text not null check (direction in ('borrow', 'repay')),
                    amount numeric(14,2) not null check (amount > 0),
                    transaction_date date not null default current_date,
                    account_id uuid references accounts(id),
                    reference text,
                    notes text,
                    created_at timestamptz not null default now()
                )
                """
            )
        )
        self.db.execute(
            text(
                "create index if not exists idx_borrowings_company_date on borrowings(company_id, transaction_date desc)"
            )
        )
        self.db.execute(
            text(
                "create index if not exists idx_borrowings_party_date on borrowings(party_id, transaction_date desc)"
            )
        )

    def list_borrowings(
        self, company_id: str | None, party_id: str | None = None, limit: int = 200
    ) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)
        self._ensure_table()

        query = """
            select
                b.id,
                b.company_id,
                b.party_id,
                p.legal_name as party_name,
                b.direction,
                b.amount,
                b.transaction_date,
                b.account_id,
                b.reference,
                b.notes,
                b.created_at
            from borrowings b
            join parties p on p.id = b.party_id
            where b.company_id = :company_id
        """
        params: dict[str, object] = {"company_id": resolved_company_id, "limit": limit}

        if party_id:
            query += " and b.party_id = :party_id"
            params["party_id"] = party_id

        query += " order by b.transaction_date desc, b.created_at desc limit :limit"
        rows = self.db.execute(text(query), params).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def summarize_borrowings(self, company_id: str | None) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)
        self._ensure_table()

        rows = self.db.execute(
            text(
                """
                select
                    b.party_id,
                    p.legal_name as party_name,
                    coalesce(sum(case when b.direction = 'borrow' then b.amount else 0 end), 0) as borrowed_amount,
                    coalesce(sum(case when b.direction = 'repay' then b.amount else 0 end), 0) as repaid_amount,
                    coalesce(sum(case when b.direction = 'borrow' then b.amount else -b.amount end), 0) as net_outstanding
                from borrowings b
                join parties p on p.id = b.party_id
                where b.company_id = :company_id
                group by b.party_id, p.legal_name
                order by net_outstanding desc, p.legal_name asc
                """
            ),
            {"company_id": resolved_company_id},
        ).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def create_borrowing(self, company_id: str | None, payload: BorrowingEntryCreate) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)
        self._ensure_table()

        direction = payload.direction.strip().lower()
        if direction not in ALLOWED_DIRECTIONS:
            raise HTTPException(status_code=422, detail="direction must be borrow or repay")
        if payload.amount <= 0:
            raise HTTPException(status_code=422, detail="amount must be greater than zero")

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

        transaction_date = payload.transaction_date or date.today()
        assert_period_open(
            db=self.db,
            company_id=resolved_company_id,
            transaction_date=transaction_date,
            action_label="Posting borrowing/settlement entry",
        )
        row = self.db.execute(
            text(
                """
                insert into borrowings (
                    company_id,
                    party_id,
                    direction,
                    amount,
                    transaction_date,
                    account_id,
                    reference,
                    notes
                ) values (
                    :company_id,
                    :party_id,
                    :direction,
                    :amount,
                    :transaction_date,
                    :account_id,
                    :reference,
                    :notes
                )
                returning id, company_id, party_id, direction, amount, transaction_date, account_id, reference, notes, created_at
                """
            ),
            {
                "company_id": resolved_company_id,
                "party_id": str(payload.party_id),
                "direction": direction,
                "amount": payload.amount,
                "transaction_date": transaction_date,
                "account_id": str(payload.account_id) if payload.account_id else None,
                "reference": payload.reference,
                "notes": payload.notes,
            },
        ).mappings().first()

        if not row:
            raise HTTPException(status_code=500, detail="Failed to create borrowing record")

        if payload.create_account_transaction and payload.account_id:
            if direction == "borrow":
                from_account_id = None
                to_account_id = str(payload.account_id)
                description = f"Borrowed from {party['legal_name']}"
            else:
                from_account_id = str(payload.account_id)
                to_account_id = None
                description = f"Repaid to {party['legal_name']}"

            if payload.notes:
                description += f" - {payload.notes}"

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
                        :from_account_id,
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
                    "from_account_id": from_account_id,
                    "to_account_id": to_account_id,
                    "amount": payload.amount,
                    "payment_mode": None,
                    "reference": payload.reference,
                    "category": "borrow_settlement",
                    "description": description,
                    "transaction_date": transaction_date,
                    "source_type": "borrowing",
                    "source_id": str(row["id"]),
                },
            )

        self.db.commit()

        return {
            **dict(row),
            "party_name": party["legal_name"],
        }
