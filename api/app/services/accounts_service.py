from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.accounts import (
    AccountCreate,
    BusinessPaymentCreate,
    AccountTransactionCreate,
    AccountUpdate,
    PeriodLockCreate,
    PeriodLockReopen,
    TransactionReverseCreate,
)
from app.services.period_lock_service import assert_period_open, ensure_period_locks_table
from app.services.documents_service import DocumentsService


class AccountsService:
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

    def _ensure_account_extensions(self) -> None:
        self.db.execute(
            text("alter table accounts add column if not exists party_id uuid references parties(id)")
        )
        self.db.execute(
            text(
                "alter table accounts add column if not exists is_company_account boolean not null default false"
            )
        )
        self.db.execute(
            text(
                "create unique index if not exists uq_accounts_one_company_account on accounts(company_id) where is_company_account = true"
            )
        )

    def _ensure_borrowings_table(self) -> None:
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

    def _sync_purchase_payment_summary(self, purchase_id: str, company_id: str) -> None:
        purchase = self.db.execute(
            text(
                """
                select id, total
                from purchases
                where id = :purchase_id and company_id = :company_id
                """
            ),
            {
                "purchase_id": purchase_id,
                "company_id": company_id,
            },
        ).mappings().first()
        if not purchase:
            return

        amount_paid = Decimal(
            str(
                self.db.execute(
                    text(
                        """
                        select coalesce(sum(amount), 0)
                        from purchase_payments
                        where purchase_id = :purchase_id
                          and company_id = :company_id
                          and reversed_at is null
                        """
                    ),
                    {
                        "purchase_id": purchase_id,
                        "company_id": company_id,
                    },
                ).scalar_one()
                or 0
            )
        )
        total = Decimal(str(purchase["total"]))
        if total - amount_paid <= Decimal("0.0001"):
            payment_status = "PAID"
        elif amount_paid > Decimal("0"):
            payment_status = "PARTIAL"
        else:
            payment_status = "UNPAID"

        self.db.execute(
            text(
                """
                update purchases
                set
                    amount_paid = :amount_paid,
                    payment_status = :payment_status
                where id = :purchase_id and company_id = :company_id
                """
            ),
            {
                "amount_paid": amount_paid,
                "payment_status": payment_status,
                "purchase_id": purchase_id,
                "company_id": company_id,
            },
        )

    def _sync_receivable_payment_summary(self, receivable_id: str, company_id: str) -> None:
        receivable = self.db.execute(
            text(
                """
                select id, invoice_id, amount_due
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
            return

        amount_due = Decimal(str(receivable["amount_due"]))
        amount_received = Decimal(
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

        if amount_received <= Decimal("0"):
            status = "UNPAID"
        elif amount_due - amount_received <= Decimal("0.0001"):
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
                "amount_received": amount_received,
                "status": status,
                "receivable_id": receivable_id,
                "company_id": company_id,
            },
        )

        self.db.execute(
            text(
                """
                update invoices
                set
                    collection_status = :status,
                    amount_received = :amount_received,
                    bad_debt_reason = case when :status = 'BAD_DEBT' then bad_debt_reason else null end
                where id = :invoice_id and company_id = :company_id
                """
            ),
            {
                "invoice_id": str(receivable["invoice_id"]) if receivable["invoice_id"] else None,
                "company_id": company_id,
                "status": status,
                "amount_received": amount_received,
            },
        )

    def _apply_source_reversal_effects(
        self,
        company_id: str,
        original_source_type: str | None,
        original_source_id: str | None,
        reversal_transaction_id: str,
        original_transaction: dict[str, object] | None = None,
    ) -> None:
        if not original_source_type or not original_source_id:
            return

        normalized_source_type = original_source_type.strip().lower()
        if normalized_source_type == "purchase_payment":
            payment = self.db.execute(
                text(
                    """
                    update purchase_payments
                    set
                        reversed_at = now(),
                        reversed_by_transaction_id = :reversal_transaction_id
                    where id = :payment_id
                      and company_id = :company_id
                      and reversed_at is null
                    returning purchase_id
                    """
                ),
                {
                    "payment_id": original_source_id,
                    "company_id": company_id,
                    "reversal_transaction_id": reversal_transaction_id,
                },
            ).mappings().first()
            if payment:
                self._sync_purchase_payment_summary(
                    purchase_id=str(payment["purchase_id"]),
                    company_id=company_id,
                )
            return

        if normalized_source_type == "purchase":
            if original_transaction and original_transaction.get("from_account_id"):
                payment = self.db.execute(
                    text(
                        """
                        with candidate as (
                            select id, purchase_id
                            from purchase_payments
                            where purchase_id = :purchase_id
                              and company_id = :company_id
                              and reversed_at is null
                              and account_id = :account_id
                              and amount = :amount
                              and payment_date = :payment_date
                            order by created_at asc
                            limit 1
                        )
                        update purchase_payments p
                        set
                            reversed_at = now(),
                            reversed_by_transaction_id = :reversal_transaction_id
                        from candidate c
                        where p.id = c.id
                        returning p.purchase_id
                        """
                    ),
                    {
                        "purchase_id": original_source_id,
                        "company_id": company_id,
                        "account_id": str(original_transaction["from_account_id"]),
                        "amount": original_transaction["amount"],
                        "payment_date": original_transaction["transaction_date"],
                        "reversal_transaction_id": reversal_transaction_id,
                    },
                ).mappings().first()
                if payment:
                    self._sync_purchase_payment_summary(
                        purchase_id=str(payment["purchase_id"]),
                        company_id=company_id,
                    )
                    return
            self._sync_purchase_payment_summary(
                purchase_id=original_source_id,
                company_id=company_id,
            )
            return

        if normalized_source_type == "receivable_payment":
            payment = self.db.execute(
                text(
                    """
                    update receivable_payments
                    set
                        reversed_at = now(),
                        reversed_by_transaction_id = :reversal_transaction_id
                    where id = :payment_id
                      and company_id = :company_id
                      and reversed_at is null
                    returning receivable_id
                    """
                ),
                {
                    "payment_id": original_source_id,
                    "company_id": company_id,
                    "reversal_transaction_id": reversal_transaction_id,
                },
            ).mappings().first()
            if payment:
                self._sync_receivable_payment_summary(
                    receivable_id=str(payment["receivable_id"]),
                    company_id=company_id,
                )
            return

        if normalized_source_type == "invoice":
            invoice = self.db.execute(
                text(
                    """
                    select id, total
                    from invoices
                    where id = :invoice_id and company_id = :company_id
                    """
                ),
                {
                    "invoice_id": original_source_id,
                    "company_id": company_id,
                },
            ).mappings().first()
            if not invoice:
                return

            amount_received = Decimal(
                str(
                    self.db.execute(
                        text(
                            """
                            select coalesce(sum(t.amount), 0)
                            from account_transactions t
                            where t.company_id = :company_id
                              and t.source_type = 'invoice'
                              and t.source_id = :invoice_id
                              and t.to_account_id is not null
                              and not exists (
                                  select 1
                                  from account_transactions r
                                  where r.company_id = t.company_id
                                    and r.reversal_of_transaction_id = t.id
                              )
                            """
                        ),
                        {
                            "company_id": company_id,
                            "invoice_id": original_source_id,
                        },
                    ).scalar_one()
                    or 0
                )
            )
            total = Decimal(str(invoice["total"]))
            if amount_received <= Decimal("0"):
                collection_status = "UNPAID"
            elif total - amount_received <= Decimal("0.0001"):
                collection_status = "SETTLED"
            else:
                collection_status = "PARTIAL"

            self.db.execute(
                text(
                    """
                    update invoices
                    set
                        amount_received = :amount_received,
                        collection_status = :collection_status,
                        bad_debt_reason = case when :collection_status = 'BAD_DEBT' then bad_debt_reason else null end
                    where id = :invoice_id and company_id = :company_id
                    """
                ),
                {
                    "invoice_id": original_source_id,
                    "company_id": company_id,
                    "amount_received": amount_received,
                    "collection_status": collection_status,
                },
            )
            self.db.execute(
                text(
                    """
                    update receivables
                    set
                        amount_received = :amount_received,
                        status = :collection_status,
                        updated_at = now()
                    where invoice_id = :invoice_id and company_id = :company_id
                    """
                ),
                {
                    "invoice_id": original_source_id,
                    "company_id": company_id,
                    "amount_received": amount_received,
                    "collection_status": collection_status,
                },
            )
            return

    def _ensure_transaction_extensions(self) -> None:
        self.db.execute(
            text(
                """
                alter table account_transactions
                add column if not exists reversal_of_transaction_id uuid references account_transactions(id)
                """
            )
        )
        self.db.execute(
            text(
                """
                create unique index if not exists uq_account_transactions_reversal_once
                on account_transactions(company_id, reversal_of_transaction_id)
                where reversal_of_transaction_id is not null
                """
            )
        )

    def _assert_company_account_uniqueness(
        self, company_id: str, is_company_account: bool, excluding_account_id: str | None = None
    ) -> None:
        if not is_company_account:
            return

        query = """
            select id
            from accounts
            where company_id = :company_id and is_company_account = true
        """
        params: dict[str, object] = {"company_id": company_id}
        if excluding_account_id:
            query += " and id <> :excluding_account_id"
            params["excluding_account_id"] = excluding_account_id

        existing = self.db.execute(text(query), params).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=422,
                detail="Exactly one company account is allowed. Disable current company account first.",
            )

    def _resolve_journal_window(
        self,
        period: str,
        from_date: str | None,
        to_date: str | None,
    ) -> tuple[str, date, date, str]:
        normalized_period = period.strip().lower()
        period_sql_map = {
            "daily": "day",
            "weekly": "week",
            "monthly": "month",
            "yearly": "year",
        }
        if normalized_period not in period_sql_map:
            raise HTTPException(status_code=422, detail="period must be daily, weekly, monthly, or yearly")

        today = date.today()
        if from_date:
            try:
                from_value = date.fromisoformat(from_date)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="from_date must be YYYY-MM-DD") from exc
        else:
            if normalized_period == "daily":
                from_value = today
            elif normalized_period == "weekly":
                from_value = today - timedelta(days=6)
            elif normalized_period == "monthly":
                from_value = today.replace(day=1)
            else:
                from_value = today.replace(month=1, day=1)

        if to_date:
            try:
                to_value = date.fromisoformat(to_date)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="to_date must be YYYY-MM-DD") from exc
        else:
            to_value = today

        if from_value > to_value:
            raise HTTPException(status_code=422, detail="from_date cannot be greater than to_date")

        return normalized_period, from_value, to_value, period_sql_map[normalized_period]

    def _parse_iso_date(self, value: str | None, field_name: str) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{field_name} must be YYYY-MM-DD") from exc

    def list_accounts(self, company_id: str | None, active_only: bool = True) -> dict:
        self._ensure_account_extensions()
        resolved_company_id = self._resolve_company_id(company_id)
        query = """
            select id, company_id, nickname, account_type, party_id, holder_name, phone, email, opening_balance, is_company_account, is_active
            from accounts
            where company_id = :company_id
        """
        params: dict[str, object] = {"company_id": resolved_company_id}
        if active_only:
            query += " and is_active = true"
        query += " order by nickname asc"

        rows = self.db.execute(text(query), params).mappings().all()
        return {"items": [dict(r) for r in rows]}

    def create_account(self, company_id: str | None, payload: AccountCreate) -> dict:
        self._ensure_account_extensions()
        resolved_company_id = self._resolve_company_id(company_id)
        self._assert_company_account_uniqueness(
            company_id=resolved_company_id,
            is_company_account=payload.is_company_account,
        )

        row = self.db.execute(
            text(
                """
                insert into accounts (
                    company_id,
                    nickname,
                    account_type,
                    party_id,
                    holder_name,
                    phone,
                    email,
                    opening_balance,
                    is_company_account
                ) values (
                    :company_id,
                    :nickname,
                    :account_type,
                    :party_id,
                    :holder_name,
                    :phone,
                    :email,
                    :opening_balance,
                    :is_company_account
                )
                returning id, company_id, nickname, account_type, party_id, holder_name, phone, email, opening_balance, is_company_account, is_active
                """
            ),
            {
                "company_id": resolved_company_id,
                "nickname": payload.nickname.strip(),
                "account_type": payload.account_type.strip(),
                "party_id": str(payload.party_id) if payload.party_id else None,
                "holder_name": payload.holder_name,
                "phone": payload.phone,
                "email": payload.email,
                "opening_balance": payload.opening_balance,
                "is_company_account": payload.is_company_account,
            },
        ).mappings().first()
        self.db.commit()

        if not row:
            raise HTTPException(status_code=500, detail="Failed to create account")
        return dict(row)

    def update_account(self, account_id: str, company_id: str | None, payload: AccountUpdate) -> dict:
        self._ensure_account_extensions()
        resolved_company_id = self._resolve_company_id(company_id)
        current = self.db.execute(
            text(
                """
                select id, company_id, nickname, account_type, party_id, holder_name, phone, email, opening_balance, is_company_account, is_active
                from accounts
                where id = :account_id and company_id = :company_id
                """
            ),
            {"account_id": account_id, "company_id": resolved_company_id},
        ).mappings().first()

        if not current:
            raise HTTPException(status_code=404, detail="Account not found")

        values = dict(current)
        changes = payload.model_dump(exclude_unset=True)
        if "nickname" in changes and changes["nickname"] is not None:
            changes["nickname"] = str(changes["nickname"]).strip()
        if "account_type" in changes and changes["account_type"] is not None:
            changes["account_type"] = str(changes["account_type"]).strip()

        if "party_id" in changes and changes["party_id"] is not None:
            changes["party_id"] = str(changes["party_id"])

        if "opening_balance" in changes and changes["opening_balance"] is not None:
            current_opening = float(current["opening_balance"])
            next_opening = float(changes["opening_balance"])
            if abs(current_opening - next_opening) > 0.0001:
                has_transactions = self.db.execute(
                    text(
                        """
                        select 1
                        from account_transactions
                        where company_id = :company_id
                          and (from_account_id = :account_id or to_account_id = :account_id)
                        limit 1
                        """
                    ),
                    {
                        "company_id": resolved_company_id,
                        "account_id": account_id,
                    },
                ).scalar_one_or_none()
                if has_transactions:
                    raise HTTPException(
                        status_code=422,
                        detail="Cannot change opening balance after transactions exist. Post an adjustment entry instead.",
                    )

        values.update(changes)
        self._assert_company_account_uniqueness(
            company_id=resolved_company_id,
            is_company_account=bool(values["is_company_account"]),
            excluding_account_id=account_id,
        )

        row = self.db.execute(
            text(
                """
                update accounts
                set
                    nickname = :nickname,
                    account_type = :account_type,
                    party_id = :party_id,
                    holder_name = :holder_name,
                    phone = :phone,
                    email = :email,
                    opening_balance = :opening_balance,
                    is_company_account = :is_company_account,
                    is_active = :is_active,
                    updated_at = now()
                where id = :account_id and company_id = :company_id
                returning id, company_id, nickname, account_type, party_id, holder_name, phone, email, opening_balance, is_company_account, is_active
                """
            ),
            {
                "account_id": account_id,
                "company_id": resolved_company_id,
                "nickname": values["nickname"],
                "account_type": values["account_type"],
                "party_id": values["party_id"],
                "holder_name": values["holder_name"],
                "phone": values["phone"],
                "email": values["email"],
                "opening_balance": values["opening_balance"],
                "is_company_account": values["is_company_account"],
                "is_active": values["is_active"],
            },
        ).mappings().first()
        self.db.commit()

        if not row:
            raise HTTPException(status_code=500, detail="Failed to update account")
        return dict(row)

    def list_transactions(
        self,
        company_id: str | None,
        limit: int = 100,
        account_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        category: str | None = None,
        source_type: str | None = None,
        business_only: bool = False,
    ) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)
        safe_limit = min(max(limit, 1), 5000)

        from_value = self._parse_iso_date(from_date, "from_date")
        to_value = self._parse_iso_date(to_date, "to_date")
        if from_value and to_value and from_value > to_value:
            raise HTTPException(status_code=422, detail="from_date cannot be greater than to_date")

        query = """
            select
                t.id,
                t.company_id,
                t.from_account_id,
                fa.nickname as from_account_name,
                t.to_account_id,
                ta.nickname as to_account_name,
                case
                    when t.from_account_id is not null and t.to_account_id is not null then 'TRANSFER'
                    when t.from_account_id is not null then 'OUTFLOW'
                    else 'INFLOW'
                end as direction,
                t.amount,
                t.payment_mode,
                t.reference,
                t.category,
                t.description,
                t.transaction_date,
                t.source_type,
                t.source_id,
                                t.reversal_of_transaction_id,
                                exists (
                                        select 1
                                        from account_transactions rev
                                        where rev.company_id = t.company_id
                                            and rev.reversal_of_transaction_id = t.id
                                ) as is_reversed,
                t.created_at
            from account_transactions t
            left join accounts fa on fa.id = t.from_account_id
            left join accounts ta on ta.id = t.to_account_id
            where t.company_id = :company_id
        """
        params: dict[str, object] = {"company_id": resolved_company_id, "limit": safe_limit}

        if business_only:
            query += " and t.category in ('business_purchase','business_billing','business_expense') and t.reversal_of_transaction_id is null"
        if account_id:
            query += " and (t.from_account_id = :account_id or t.to_account_id = :account_id)"
            params["account_id"] = account_id
        if from_value:
            query += " and t.transaction_date >= :from_date"
            params["from_date"] = from_value
        if to_value:
            query += " and t.transaction_date <= :to_date"
            params["to_date"] = to_value
        if category and category.strip():
            query += " and coalesce(t.category, '') ilike :category"
            params["category"] = f"%{category.strip()}%"
        if source_type and source_type.strip():
            query += " and coalesce(t.source_type, '') ilike :source_type"
            params["source_type"] = f"%{source_type.strip()}%"

        query += " order by t.transaction_date desc, t.created_at desc limit :limit"

        rows = self.db.execute(
            text(query),
            params,
        ).mappings().all()
        return {"items": [dict(r) for r in rows]}

    def account_tally(
        self,
        company_id: str | None,
        as_of: str | None = None,
        include_inactive: bool = False,
    ) -> dict:
        self._ensure_account_extensions()
        resolved_company_id = self._resolve_company_id(company_id)
        as_of_date = self._parse_iso_date(as_of, "as_of") or date.today()

        query = """
            select
                a.id as account_id,
                a.nickname as account_name,
                a.account_type,
                a.is_company_account,
                a.opening_balance,
                coalesce(totals.total_inflow, 0) as total_inflow,
                coalesce(totals.total_outflow, 0) as total_outflow,
                a.opening_balance
                    + coalesce(totals.total_inflow, 0)
                    - coalesce(totals.total_outflow, 0) as current_balance,
                coalesce(totals.transaction_count, 0) as transaction_count,
                totals.last_transaction_date
            from accounts a
            left join (
                select
                    account_id,
                    sum(inflow) as total_inflow,
                    sum(outflow) as total_outflow,
                    sum(entry_count) as transaction_count,
                    max(transaction_date) as last_transaction_date
                from (
                    select
                        to_account_id as account_id,
                        amount as inflow,
                        0::numeric as outflow,
                        1 as entry_count,
                        transaction_date
                    from account_transactions
                    where company_id = :company_id
                      and to_account_id is not null
                      and transaction_date <= :as_of_date

                    union all

                    select
                        from_account_id as account_id,
                        0::numeric as inflow,
                        amount as outflow,
                        1 as entry_count,
                        transaction_date
                    from account_transactions
                    where company_id = :company_id
                      and from_account_id is not null
                      and transaction_date <= :as_of_date
                ) ledger
                group by account_id
            ) totals on totals.account_id = a.id
            where a.company_id = :company_id
        """
        if not include_inactive:
            query += " and a.is_active = true"

        query += " order by a.nickname asc"

        rows = self.db.execute(
            text(query),
            {
                "company_id": resolved_company_id,
                "as_of_date": as_of_date,
            },
        ).mappings().all()

        items = [dict(r) for r in rows]
        total_opening = sum(float(item["opening_balance"]) for item in items)
        total_inflow = sum(float(item["total_inflow"]) for item in items)
        total_outflow = sum(float(item["total_outflow"]) for item in items)
        total_current = sum(float(item["current_balance"]) for item in items)

        return {
            "as_of": as_of_date,
            "total_opening_balance": total_opening,
            "total_inflow": total_inflow,
            "total_outflow": total_outflow,
            "total_current_balance": total_current,
            "items": items,
        }

    def list_audit_journal(
        self,
        company_id: str | None,
        period: str,
        from_date: str | None = None,
        to_date: str | None = None,
        category: str | None = None,
        source_type: str | None = None,
        limit: int = 2000,
    ) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)
        normalized_period, from_value, to_value, period_sql = self._resolve_journal_window(
            period=period,
            from_date=from_date,
            to_date=to_date,
        )

        safe_limit = min(max(limit, 1), 10000)
        params: dict[str, object] = {
            "company_id": resolved_company_id,
            "from_date": from_value,
            "to_date": to_value,
            "limit": safe_limit,
        }

        query = f"""
            select
                t.id as transaction_id,
                t.transaction_date,
                to_char(date_trunc('{period_sql}', t.transaction_date::timestamp), 'YYYY-MM-DD') as period_key,
                case
                    when t.from_account_id is not null and t.to_account_id is not null then 'TRANSFER'
                    when t.from_account_id is not null then 'OUTFLOW'
                    else 'INFLOW'
                end as direction,
                t.amount,
                t.from_account_id,
                fa.nickname as from_account_name,
                t.to_account_id,
                ta.nickname as to_account_name,
                t.payment_mode,
                t.reference,
                t.category,
                t.description,
                t.source_type,
                t.source_id,
                                t.reversal_of_transaction_id,
                                exists (
                                        select 1
                                        from account_transactions rev
                                        where rev.company_id = t.company_id
                                            and rev.reversal_of_transaction_id = t.id
                                ) as is_reversed,
                t.created_at
            from account_transactions t
            left join accounts fa on fa.id = t.from_account_id
            left join accounts ta on ta.id = t.to_account_id
            where t.company_id = :company_id
              and t.transaction_date between :from_date and :to_date
        """

        if category:
            query += " and t.category = :category"
            params["category"] = category

        if source_type:
            query += " and t.source_type = :source_type"
            params["source_type"] = source_type

        query += " order by t.transaction_date desc, t.created_at desc limit :limit"

        rows = self.db.execute(text(query), params).mappings().all()
        items = [dict(r) for r in rows]

        bucket_map: dict[str, dict[str, float | int | str]] = {}
        for item in items:
            key = str(item["period_key"])
            if key not in bucket_map:
                bucket_map[key] = {
                    "period_key": key,
                    "entry_count": 0,
                    "total_inflow": 0.0,
                    "total_outflow": 0.0,
                    "total_transfer": 0.0,
                }

            bucket = bucket_map[key]
            amount = float(item["amount"])
            direction = str(item["direction"])

            bucket["entry_count"] = int(bucket["entry_count"]) + 1
            if direction == "INFLOW":
                bucket["total_inflow"] = float(bucket["total_inflow"]) + amount
            elif direction == "OUTFLOW":
                bucket["total_outflow"] = float(bucket["total_outflow"]) + amount
            else:
                bucket["total_transfer"] = float(bucket["total_transfer"]) + amount

        buckets = []
        for key in sorted(bucket_map.keys(), reverse=True):
            bucket = bucket_map[key]
            total_inflow = float(bucket["total_inflow"])
            total_outflow = float(bucket["total_outflow"])
            buckets.append(
                {
                    "period_key": bucket["period_key"],
                    "entry_count": int(bucket["entry_count"]),
                    "total_inflow": total_inflow,
                    "total_outflow": total_outflow,
                    "total_transfer": float(bucket["total_transfer"]),
                    "net_flow": total_inflow - total_outflow,
                }
            )

        return {
            "period": normalized_period,
            "from_date": from_value,
            "to_date": to_value,
            "items": items,
            "buckets": buckets,
        }

    def create_transaction(self, company_id: str | None, payload: AccountTransactionCreate) -> dict:
        self._ensure_transaction_extensions()
        resolved_company_id = self._resolve_company_id(company_id)
        if not payload.from_account_id and not payload.to_account_id:
            raise HTTPException(status_code=422, detail="Either from_account_id or to_account_id is required")
        if payload.amount <= 0:
            raise HTTPException(status_code=422, detail="Amount must be greater than zero")
        if payload.from_account_id and payload.to_account_id and payload.from_account_id == payload.to_account_id:
            raise HTTPException(status_code=422, detail="from_account_id and to_account_id cannot be the same")

        if payload.from_account_id:
            from_account = self.db.execute(
                text(
                    """
                    select id
                    from accounts
                    where id = :account_id and company_id = :company_id and is_active = true
                    """
                ),
                {
                    "account_id": str(payload.from_account_id),
                    "company_id": resolved_company_id,
                },
            ).scalar_one_or_none()
            if not from_account:
                raise HTTPException(status_code=404, detail="From account not found or inactive")

        if payload.to_account_id:
            to_account = self.db.execute(
                text(
                    """
                    select id
                    from accounts
                    where id = :account_id and company_id = :company_id and is_active = true
                    """
                ),
                {
                    "account_id": str(payload.to_account_id),
                    "company_id": resolved_company_id,
                },
            ).scalar_one_or_none()
            if not to_account:
                raise HTTPException(status_code=404, detail="To account not found or inactive")

        transaction_date = payload.transaction_date or date.today()
        assert_period_open(
            db=self.db,
            company_id=resolved_company_id,
            transaction_date=transaction_date,
            action_label="Posting account transaction",
        )
        row = self.db.execute(
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
                    transaction_date
                ) values (
                    :company_id,
                    :from_account_id,
                    :to_account_id,
                    :amount,
                    :payment_mode,
                    :reference,
                    :category,
                    :description,
                    :transaction_date
                )
                returning
                    id,
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
                    source_id,
                    reversal_of_transaction_id,
                    created_at
                """
            ),
            {
                "company_id": resolved_company_id,
                "from_account_id": payload.from_account_id,
                "to_account_id": payload.to_account_id,
                "amount": payload.amount,
                "payment_mode": payload.payment_mode,
                "reference": payload.reference,
                "category": payload.category,
                "description": payload.description,
                "transaction_date": transaction_date,
            },
        ).mappings().first()
        self.db.commit()

        if not row:
            raise HTTPException(status_code=500, detail="Failed to create transaction")
        return dict(row)

    def create_business_payment(self, company_id: str | None, payload: BusinessPaymentCreate) -> dict:
        self._ensure_account_extensions()
        self._ensure_borrowings_table()
        self._ensure_transaction_extensions()
        resolved_company_id = self._resolve_company_id(company_id)

        purpose = payload.purpose.strip().lower()
        if purpose not in {"purchase", "billing", "expense"}:
            raise HTTPException(status_code=422, detail="purpose must be purchase, billing, or expense")

        if payload.amount <= 0:
            raise HTTPException(status_code=422, detail="amount must be greater than zero")

        related_party_id: str | None = str(payload.related_party_id) if payload.related_party_id else None
        related_party_name: str | None = None
        if purpose in {"purchase", "billing"} and not related_party_id:
            raise HTTPException(
                status_code=422,
                detail="related_party_id is required for purchase or billing payments",
            )
        if related_party_id:
            related_party = self.db.execute(
                text(
                    """
                    select id, legal_name
                    from parties
                    where id = :party_id and company_id = :company_id and is_active = true
                    """
                ),
                {
                    "party_id": related_party_id,
                    "company_id": resolved_company_id,
                },
            ).mappings().first()
            if not related_party:
                raise HTTPException(status_code=404, detail="Related party not found")
            related_party_name = str(related_party["legal_name"])

        account = self.db.execute(
            text(
                """
                select id, nickname, party_id, is_company_account
                from accounts
                where id = :account_id and company_id = :company_id and is_active = true
                """
            ),
            {"account_id": str(payload.from_account_id), "company_id": resolved_company_id},
        ).mappings().first()
        if not account:
            raise HTTPException(status_code=404, detail="Source account not found")

        if not account["is_company_account"] and payload.create_borrowing and not account["party_id"]:
            raise HTTPException(
                status_code=422,
                detail="Non-company account must be linked to a party to auto-record borrowing",
            )

        transaction_date = payload.transaction_date or date.today()
        assert_period_open(
            db=self.db,
            company_id=resolved_company_id,
            transaction_date=transaction_date,
            action_label="Posting business payment",
        )
        tx = self.db.execute(
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
                    null,
                    :amount,
                    :payment_mode,
                    :reference,
                    :category,
                    :description,
                    :transaction_date,
                    :source_type,
                    :source_id
                )
                returning
                    id,
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
                    source_id,
                    reversal_of_transaction_id,
                    created_at
                """
            ),
            {
                "company_id": resolved_company_id,
                "from_account_id": str(payload.from_account_id),
                "amount": payload.amount,
                "payment_mode": payload.payment_mode,
                "reference": payload.reference,
                "category": f"business_{purpose}",
                "description": payload.notes
                or (
                    f"{purpose.title()} payment"
                    + (f" - {related_party_name}" if related_party_name else "")
                ),
                "transaction_date": transaction_date,
                "source_type": purpose,
                "source_id": related_party_id,
            },
        ).mappings().first()

        if not tx:
            raise HTTPException(status_code=500, detail="Failed to create business payment")

        borrowing_id: str | None = None
        if not account["is_company_account"] and payload.create_borrowing:
            borrowing = self.db.execute(
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
                        'borrow',
                        :amount,
                        :transaction_date,
                        :account_id,
                        :reference,
                        :notes
                    )
                    returning id
                    """
                ),
                {
                    "company_id": resolved_company_id,
                    "party_id": str(account["party_id"]),
                    "amount": payload.amount,
                    "transaction_date": transaction_date,
                    "account_id": str(payload.from_account_id),
                    "reference": payload.reference,
                    "notes": payload.notes or f"Auto-captured borrowing for {purpose} payment",
                },
            ).mappings().first()
            borrowing_id = str(borrowing["id"]) if borrowing else None

        DocumentsService(self.db).add_attachments(
            "business_payment", str(tx["id"]), resolved_company_id, payload.attachments
        )
        self.db.commit()
        return {
            "account_transaction": dict(tx),
            "borrowing_id": borrowing_id,
        }

    def reverse_transaction(
        self,
        transaction_id: str,
        company_id: str | None,
        payload: TransactionReverseCreate,
    ) -> dict:
        self._ensure_transaction_extensions()
        resolved_company_id = self._resolve_company_id(company_id)

        original = self.db.execute(
            text(
                """
                select
                    id,
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
                    source_id,
                    reversal_of_transaction_id,
                    created_at
                from account_transactions
                where id = :transaction_id and company_id = :company_id
                """
            ),
            {
                "transaction_id": transaction_id,
                "company_id": resolved_company_id,
            },
        ).mappings().first()
        if not original:
            raise HTTPException(status_code=404, detail="Transaction not found")

        if original["reversal_of_transaction_id"]:
            raise HTTPException(status_code=422, detail="Reversal transactions cannot be reversed again")

        already_reversed = self.db.execute(
            text(
                """
                select id
                from account_transactions
                where company_id = :company_id and reversal_of_transaction_id = :transaction_id
                limit 1
                """
            ),
            {
                "company_id": resolved_company_id,
                "transaction_id": transaction_id,
            },
        ).scalar_one_or_none()
        if already_reversed:
            raise HTTPException(status_code=422, detail="Transaction already reversed")

        reversal_date = payload.transaction_date or date.today()
        assert_period_open(
            db=self.db,
            company_id=resolved_company_id,
            transaction_date=reversal_date,
            action_label="Posting transaction reversal",
        )

        reverse_reference = payload.reference or original["reference"]
        reverse_description = payload.notes or f"Reversal of transaction {original['id']}"

        reversal = self.db.execute(
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
                    source_id,
                    reversal_of_transaction_id
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
                    :source_id,
                    :reversal_of_transaction_id
                )
                returning
                    id,
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
                    source_id,
                    reversal_of_transaction_id,
                    created_at
                """
            ),
            {
                "company_id": resolved_company_id,
                "from_account_id": original["to_account_id"],
                "to_account_id": original["from_account_id"],
                "amount": original["amount"],
                "payment_mode": original["payment_mode"],
                "reference": reverse_reference,
                "category": original["category"],
                "description": reverse_description,
                "transaction_date": reversal_date,
                "source_type": "reversal",
                "source_id": original["id"],
                "reversal_of_transaction_id": original["id"],
            },
        ).mappings().first()

        if reversal:
            self._apply_source_reversal_effects(
                company_id=resolved_company_id,
                original_source_type=(str(original["source_type"]) if original["source_type"] else None),
                original_source_id=(str(original["source_id"]) if original["source_id"] else None),
                reversal_transaction_id=str(reversal["id"]),
                original_transaction=dict(original),
            )
        self.db.commit()

        if not reversal:
            raise HTTPException(status_code=500, detail="Failed to create reversal transaction")

        original_out = dict(original)
        original_out["direction"] = (
            "TRANSFER"
            if original["from_account_id"] and original["to_account_id"]
            else "OUTFLOW"
            if original["from_account_id"]
            else "INFLOW"
        )
        reversal_out = dict(reversal)
        reversal_out["direction"] = (
            "TRANSFER"
            if reversal["from_account_id"] and reversal["to_account_id"]
            else "OUTFLOW"
            if reversal["from_account_id"]
            else "INFLOW"
        )
        return {
            "original_transaction": original_out,
            "reversal_transaction": reversal_out,
        }

    def list_period_locks(self, company_id: str | None, include_inactive: bool = False) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)
        ensure_period_locks_table(self.db)

        query = """
            select
                id,
                company_id,
                period_start,
                period_end,
                reason,
                closed_by,
                is_active,
                created_at,
                reopened_at,
                reopened_by,
                reopen_reason
            from accounting_period_locks
            where company_id = :company_id
        """
        params: dict[str, object] = {"company_id": resolved_company_id}
        if not include_inactive:
            query += " and is_active = true"
        query += " order by period_start desc, created_at desc"

        rows = self.db.execute(text(query), params).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def close_period(self, company_id: str | None, payload: PeriodLockCreate) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)
        ensure_period_locks_table(self.db)

        if payload.period_start > payload.period_end:
            raise HTTPException(status_code=422, detail="period_start cannot be after period_end")

        overlap = self.db.execute(
            text(
                """
                select id
                from accounting_period_locks
                where company_id = :company_id
                  and is_active = true
                  and daterange(period_start, period_end, '[]')
                      && daterange(:period_start, :period_end, '[]')
                limit 1
                """
            ),
            {
                "company_id": resolved_company_id,
                "period_start": payload.period_start,
                "period_end": payload.period_end,
            },
        ).scalar_one_or_none()
        if overlap:
            raise HTTPException(status_code=422, detail="An active period lock already overlaps this range")

        row = self.db.execute(
            text(
                """
                insert into accounting_period_locks (
                    company_id,
                    period_start,
                    period_end,
                    reason,
                    closed_by,
                    is_active
                ) values (
                    :company_id,
                    :period_start,
                    :period_end,
                    :reason,
                    :closed_by,
                    true
                )
                returning
                    id,
                    company_id,
                    period_start,
                    period_end,
                    reason,
                    closed_by,
                    is_active,
                    created_at,
                    reopened_at,
                    reopened_by,
                    reopen_reason
                """
            ),
            {
                "company_id": resolved_company_id,
                "period_start": payload.period_start,
                "period_end": payload.period_end,
                "reason": payload.reason,
                "closed_by": payload.closed_by,
            },
        ).mappings().first()
        self.db.commit()
        if not row:
            raise HTTPException(status_code=500, detail="Failed to close period")
        return dict(row)

    def reopen_period(self, lock_id: str, company_id: str | None, payload: PeriodLockReopen) -> dict:
        resolved_company_id = self._resolve_company_id(company_id)
        ensure_period_locks_table(self.db)

        row = self.db.execute(
            text(
                """
                update accounting_period_locks
                set
                    is_active = false,
                    reopened_at = now(),
                    reopened_by = :reopened_by,
                    reopen_reason = :reopen_reason
                where id = :lock_id and company_id = :company_id and is_active = true
                returning
                    id,
                    company_id,
                    period_start,
                    period_end,
                    reason,
                    closed_by,
                    is_active,
                    created_at,
                    reopened_at,
                    reopened_by,
                    reopen_reason
                """
            ),
            {
                "lock_id": lock_id,
                "company_id": resolved_company_id,
                "reopened_by": payload.reopened_by,
                "reopen_reason": payload.reopen_reason,
            },
        ).mappings().first()
        self.db.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Active period lock not found")
        return dict(row)

    def export_transactions_csv(
        self,
        company_id: str | None,
        limit: int = 1000,
        account_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        category: str | None = None,
        source_type: str | None = None,
    ) -> str:
        data = self.list_transactions(
            company_id=company_id,
            limit=limit,
            account_id=account_id,
            from_date=from_date,
            to_date=to_date,
            category=category,
            source_type=source_type,
        )
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "transaction_date",
                "direction",
                "amount",
                "from_account",
                "to_account",
                "payment_mode",
                "reference",
                "category",
                "source_type",
                "description",
                "created_at",
            ]
        )
        for item in data["items"]:
            writer.writerow(
                [
                    item.get("transaction_date"),
                    item.get("direction"),
                    item.get("amount"),
                    item.get("from_account_name") or item.get("from_account_id") or "",
                    item.get("to_account_name") or item.get("to_account_id") or "",
                    item.get("payment_mode") or "",
                    item.get("reference") or "",
                    item.get("category") or "",
                    item.get("source_type") or "",
                    item.get("description") or "",
                    item.get("created_at"),
                ]
            )
        return output.getvalue()

    def export_journal_csv(
        self,
        company_id: str | None,
        period: str,
        from_date: str | None = None,
        to_date: str | None = None,
        category: str | None = None,
        source_type: str | None = None,
        limit: int = 5000,
    ) -> str:
        data = self.list_audit_journal(
            company_id=company_id,
            period=period,
            from_date=from_date,
            to_date=to_date,
            category=category,
            source_type=source_type,
            limit=limit,
        )

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "transaction_date",
                "period_key",
                "direction",
                "amount",
                "from_account",
                "to_account",
                "payment_mode",
                "reference",
                "category",
                "description",
                "source_type",
                "source_id",
                "created_at",
            ]
        )
        for item in data["items"]:
            writer.writerow(
                [
                    item.get("transaction_date"),
                    item.get("period_key"),
                    item.get("direction"),
                    item.get("amount"),
                    item.get("from_account_name") or item.get("from_account_id") or "",
                    item.get("to_account_name") or item.get("to_account_id") or "",
                    item.get("payment_mode") or "",
                    item.get("reference") or "",
                    item.get("category") or "",
                    item.get("description") or "",
                    item.get("source_type") or "",
                    item.get("source_id") or "",
                    item.get("created_at"),
                ]
            )
        return output.getvalue()
