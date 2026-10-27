from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from io import StringIO

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate, PurchaseReceiptConfirm
from app.services.period_lock_service import assert_period_open
from app.services.masters_service import MastersService
from app.services.documents_service import DocumentsService


class PurchasesService:
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
                create table if not exists purchases (
                    id uuid primary key default gen_random_uuid(),
                    company_id uuid not null references companies(id),
                    vendor_party_id uuid not null references parties(id),
                    bill_number text,
                    purchase_date date not null default current_date,
                    subtotal numeric(14,2) not null default 0,
                    gst_total numeric(14,2) not null default 0,
                    total numeric(14,2) not null default 0,
                    amount_paid numeric(14,2) not null default 0,
                    payment_status text not null default 'UNPAID' check (payment_status in ('UNPAID','PARTIAL','PAID')),
                    payment_mode text,
                    account_id uuid references accounts(id),
                    reference text,
                    due_date date,
                    notes text,
                    receipt_type text not null default 'PRODUCT' check (receipt_type in ('PRODUCT','STOCK','SERVICE')),
                    receipt_status text not null default 'PENDING' check (receipt_status in ('PENDING','RECEIVED')),
                    received_at timestamptz,
                    received_notes text,
                    status text not null default 'POSTED',
                    document_id uuid,
                    created_by uuid references user_profiles(id),
                    created_at timestamptz not null default now()
                )
                """
            )
        )
        self.db.execute(
            text("alter table purchases add column if not exists amount_paid numeric(14,2) not null default 0")
        )
        self.db.execute(
            text("alter table purchases add column if not exists payment_status text not null default 'UNPAID'")
        )
        self.db.execute(text("alter table purchases add column if not exists due_date date"))
        self.db.execute(text("alter table purchases add column if not exists notes text"))
        self.db.execute(
            text("alter table purchases add column if not exists receipt_type text not null default 'PRODUCT'")
        )
        self.db.execute(
            text("alter table purchases add column if not exists receipt_status text not null default 'PENDING'")
        )
        self.db.execute(text("alter table purchases add column if not exists received_at timestamptz"))
        self.db.execute(text("alter table purchases add column if not exists received_notes text"))
        self.db.execute(text("alter table purchases add column if not exists line_items jsonb not null default '[]'::jsonb"))

        self.db.execute(
            text(
                """
                create index if not exists idx_purchases_company_date
                on purchases(company_id, purchase_date desc, created_at desc)
                """
            )
        )
        self.db.execute(
            text(
                """
                create index if not exists idx_purchases_receipt_status
                on purchases(company_id, receipt_status, receipt_type)
                """
            )
        )

        self.db.execute(
            text(
                """
                create table if not exists account_transactions (
                    id uuid primary key default gen_random_uuid(),
                    company_id uuid not null references companies(id),
                    from_account_id uuid references accounts(id),
                    to_account_id uuid references accounts(id),
                    amount numeric(14,2) not null check (amount > 0),
                    payment_mode text,
                    reference text,
                    category text,
                    description text,
                    transaction_date date not null default current_date,
                    source_type text,
                    source_id uuid,
                    created_by uuid references user_profiles(id),
                    created_at timestamptz not null default now(),
                    check (from_account_id is not null or to_account_id is not null)
                )
                """
            )
        )

        self.db.execute(
            text(
                """
                create table if not exists purchase_payments (
                    id uuid primary key default gen_random_uuid(),
                    purchase_id uuid not null references purchases(id) on delete cascade,
                    company_id uuid not null references companies(id),
                    account_id uuid not null references accounts(id),
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
        self.db.execute(text("alter table purchase_payments add column if not exists idempotency_key text"))
        self.db.execute(text("alter table purchase_payments add column if not exists reversed_at timestamptz"))
        self.db.execute(
            text(
                """
                alter table purchase_payments
                add column if not exists reversed_by_transaction_id uuid references account_transactions(id)
                """
            )
        )
        self.db.execute(
            text(
                """
                create index if not exists idx_purchase_payments_purchase
                on purchase_payments(purchase_id, payment_date desc, created_at desc)
                """
            )
        )
        self.db.execute(
            text(
                """
                create unique index if not exists uq_purchase_payments_idempotency
                on purchase_payments(company_id, idempotency_key)
                where idempotency_key is not null
                """
            )
        )

    def _sync_purchase_payment_summary(self, purchase_id: str, company_id: str) -> None:
        payment_total = self.db.execute(
            text(
                """
                select coalesce(sum(amount), 0)
                from purchase_payments
                where purchase_id = :purchase_id and company_id = :company_id and reversed_at is null
                """
            ),
            {
                "purchase_id": purchase_id,
                "company_id": company_id,
            },
        ).scalar_one()
        amount_paid = Decimal(str(payment_total or 0))

        purchase = self.db.execute(
            text(
                """
                select total
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
            raise HTTPException(status_code=404, detail="Purchase not found")

        total = Decimal(str(purchase["total"]))
        payment_status = self._derive_payment_status(total=total, amount_paid=amount_paid)
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

    def _derive_payment_status(self, total: Decimal, amount_paid: Decimal) -> str:
        if total - amount_paid <= Decimal("0.0001"):
            return "PAID"
        if amount_paid > Decimal("0"):
            return "PARTIAL"
        return "UNPAID"

    def _normalize_receipt_type(self, receipt_type: str | None) -> str:
        normalized = (receipt_type or "PRODUCT").strip().upper()
        if normalized not in {"PRODUCT", "STOCK", "SERVICE"}:
            raise HTTPException(status_code=422, detail="receipt_type must be PRODUCT, STOCK, or SERVICE")
        return normalized

    def list_purchases(
        self,
        company_id: str | None,
        vendor_party_id: str | None = None,
        payment_status: str | None = None,
    ) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        query = """
            select
                p.id,
                p.company_id,
                p.vendor_party_id,
                v.legal_name as vendor_name,
                p.bill_number,
                p.purchase_date,
                p.subtotal,
                p.gst_total,
                p.total,
                p.amount_paid,
                greatest(p.total - p.amount_paid, 0) as balance_amount,
                p.payment_status,
                p.payment_mode,
                p.account_id,
                p.reference,
                p.due_date,
                p.notes,
                p.receipt_type,
                p.receipt_status,
                p.received_at,
                p.received_notes,
                p.status,
                p.line_items,
                p.created_at
            from purchases p
            join parties v on v.id = p.vendor_party_id
            where p.company_id = :company_id
        """
        params: dict[str, object] = {"company_id": resolved_company_id}

        if vendor_party_id:
            query += " and p.vendor_party_id = :vendor_party_id"
            params["vendor_party_id"] = vendor_party_id

        normalized_status: str | None = None
        if payment_status:
            normalized_status = payment_status.strip().upper()
            if normalized_status not in {"UNPAID", "PARTIAL", "PAID"}:
                raise HTTPException(status_code=422, detail="payment_status must be UNPAID, PARTIAL, or PAID")
            query += " and p.payment_status = :payment_status"
            params["payment_status"] = normalized_status

        query += " order by p.purchase_date desc, p.created_at desc limit 500"

        rows = self.db.execute(text(query), params).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def create_purchase(self, company_id: str | None, payload: PurchaseCreate) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        vendor = self.db.execute(
            text(
                """
                select id, legal_name, party_type
                from parties
                where id = :vendor_party_id and company_id = :company_id and is_active = true
                """
            ),
            {"vendor_party_id": str(payload.vendor_party_id), "company_id": resolved_company_id},
        ).mappings().first()
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor party not found")

        line_items = []
        if payload.lines:
            MastersService(self.db).apply_hsn_rates(payload.lines, resolved_company_id)
            subtotal = Decimal("0")
            gst_total = Decimal("0")
            for line in payload.lines:
                taxable = (line.quantity * line.rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                gst = (taxable * line.gst_rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                line_items.append({**line.model_dump(mode="json"), "taxable": str(taxable), "gst_amount": str(gst), "total": str(taxable + gst)})
                subtotal += taxable
                gst_total += gst
            payload.subtotal = float(subtotal)
            payload.gst_total = float(gst_total)
            payload.total = float(subtotal + gst_total)

        if payload.subtotal < 0 or payload.gst_total < 0:
            raise HTTPException(status_code=422, detail="subtotal and gst_total must be non-negative")

        total = payload.total if payload.total is not None else payload.subtotal + payload.gst_total
        if total <= 0:
            raise HTTPException(status_code=422, detail="total must be greater than zero")

        amount_paid = Decimal(str(payload.amount_paid))
        total_amount = Decimal(str(total))
        if amount_paid < 0:
            raise HTTPException(status_code=422, detail="amount_paid cannot be negative")
        if amount_paid - total_amount > Decimal("0.0001"):
            raise HTTPException(status_code=422, detail="amount_paid cannot exceed total")
        if amount_paid > 0 and not payload.account_id:
            raise HTTPException(
                status_code=422,
                detail="account_id is required when amount_paid > 0",
            )

        if amount_paid > 0 and not payload.payment_mode:
            raise HTTPException(status_code=422, detail="payment_mode required when amount_paid > 0")

        if payload.account_id:
            account = self.db.execute(
                text(
                    """
                    select id
                    from accounts
                    where id = :account_id and company_id = :company_id and is_active = true
                    """
                ),
                {"account_id": str(payload.account_id), "company_id": resolved_company_id},
            ).scalar_one_or_none()
            if not account:
                raise HTTPException(status_code=404, detail="Account not found")

        payment_status = self._derive_payment_status(total=total_amount, amount_paid=amount_paid)
        receipt_type = self._normalize_receipt_type(payload.receipt_type)
        purchase_date = payload.purchase_date or date.today()
        assert_period_open(
            db=self.db,
            company_id=resolved_company_id,
            transaction_date=purchase_date,
            action_label="Posting purchase",
        )

        row = self.db.execute(
            text(
                """
                insert into purchases (
                    company_id,
                    vendor_party_id,
                    bill_number,
                    purchase_date,
                    subtotal,
                    gst_total,
                    total,
                    amount_paid,
                    payment_status,
                    payment_mode,
                    account_id,
                    reference,
                    due_date,
                    notes,
                    receipt_type,
                    receipt_status,
                    received_at,
                    received_notes,
                    status,
                    line_items
                ) values (
                    :company_id,
                    :vendor_party_id,
                    :bill_number,
                    :purchase_date,
                    :subtotal,
                    :gst_total,
                    :total,
                    :amount_paid,
                    :payment_status,
                    :payment_mode,
                    :account_id,
                    :reference,
                    :due_date,
                    :notes,
                    :receipt_type,
                    'PENDING',
                    null,
                    null,
                    'POSTED',
                    cast(:line_items as jsonb)
                )
                returning id, company_id, vendor_party_id, bill_number, purchase_date, subtotal, gst_total, total, amount_paid, payment_status, payment_mode, account_id, reference, due_date, notes, receipt_type, receipt_status, received_at, received_notes, status, line_items, created_at
                """
            ),
            {
                "company_id": resolved_company_id,
                "vendor_party_id": str(payload.vendor_party_id),
                "bill_number": payload.bill_number,
                "purchase_date": purchase_date,
                "subtotal": payload.subtotal,
                "gst_total": payload.gst_total,
                "total": total,
                "amount_paid": amount_paid,
                "payment_status": payment_status,
                "payment_mode": payload.payment_mode,
                "account_id": str(payload.account_id) if payload.account_id else None,
                "reference": payload.reference,
                "due_date": payload.due_date,
                "notes": payload.notes,
                "receipt_type": receipt_type,
                "line_items": json.dumps(line_items),
            },
        ).mappings().first()

        if not row:
            raise HTTPException(status_code=500, detail="Failed to create purchase")

        purchase = dict(row)

        if amount_paid > Decimal("0"):
            payment_mode = (payload.payment_mode or "").strip()
            if not payment_mode:
                raise HTTPException(status_code=422, detail="payment_mode required when amount_paid > 0")

            payment_row = self.db.execute(
                text(
                    """
                    insert into purchase_payments (
                        purchase_id,
                        company_id,
                        account_id,
                        amount,
                        payment_mode,
                        idempotency_key,
                        reference,
                        payment_date,
                        notes
                    ) values (
                        :purchase_id,
                        :company_id,
                        :account_id,
                        :amount,
                        :payment_mode,
                        :idempotency_key,
                        :reference,
                        :payment_date,
                        :notes
                    )
                    returning id
                    """
                ),
                {
                    "purchase_id": str(purchase["id"]),
                    "company_id": resolved_company_id,
                    "account_id": str(payload.account_id),
                    "amount": amount_paid,
                    "payment_mode": payment_mode,
                    "idempotency_key": f"purchase-create:{purchase['id']}",
                    "reference": payload.reference,
                    "payment_date": purchase_date,
                    "notes": payload.notes,
                },
            ).mappings().first()

            if not payment_row:
                raise HTTPException(status_code=500, detail="Failed to create purchase payment")

            self.db.execute(
                text(
                    """
                    insert into account_transactions (
                        company_id,
                        from_account_id,
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
                        :amount,
                        :payment_mode,
                        :reference,
                        'purchase_payment',
                        :description,
                        :transaction_date,
                        'purchase_payment',
                        :source_id
                    )
                    """
                ),
                {
                    "company_id": resolved_company_id,
                    "from_account_id": str(payload.account_id),
                    "amount": amount_paid,
                    "payment_mode": payment_mode,
                    "reference": payload.reference,
                    "description": payload.notes or "Vendor purchase payment",
                    "transaction_date": purchase_date,
                    "source_id": str(payment_row["id"]),
                },
            )

        self._sync_purchase_payment_summary(
            purchase_id=str(purchase["id"]),
            company_id=resolved_company_id,
        )

        DocumentsService(self.db).add_attachments(
            "purchase", str(purchase["id"]), resolved_company_id, payload.attachments
        )
        self.db.commit()

        result = self.db.execute(
            text(
                """
                select
                    p.id,
                    p.company_id,
                    p.vendor_party_id,
                    v.legal_name as vendor_name,
                    p.bill_number,
                    p.purchase_date,
                    p.subtotal,
                    p.gst_total,
                    p.total,
                    p.amount_paid,
                    greatest(p.total - p.amount_paid, 0) as balance_amount,
                    p.payment_status,
                    p.payment_mode,
                    p.account_id,
                    p.reference,
                    p.due_date,
                    p.notes,
                    p.receipt_type,
                    p.receipt_status,
                    p.received_at,
                    p.received_notes,
                    p.status,
                    p.created_at
                from purchases p
                join parties v on v.id = p.vendor_party_id
                where p.id = :purchase_id and p.company_id = :company_id
                """
            ),
            {"purchase_id": str(purchase["id"]), "company_id": resolved_company_id},
        ).mappings().first()

        if not result:
            raise HTTPException(status_code=500, detail="Failed to load created purchase")

        return dict(result)

    def add_purchase_payment(
        self,
        purchase_id: str,
        company_id: str | None,
        payload: PurchasePaymentCreate,
    ) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        if payload.amount <= 0:
            raise HTTPException(status_code=422, detail="amount must be greater than zero")

        payment_mode = payload.payment_mode.strip()
        if not payment_mode:
            raise HTTPException(status_code=422, detail="payment_mode is required")

        purchase = self.db.execute(
            text(
                """
                select id, company_id, total, amount_paid, payment_status
                from purchases
                where id = :purchase_id and company_id = :company_id
                """
            ),
            {"purchase_id": purchase_id, "company_id": resolved_company_id},
        ).mappings().first()
        if not purchase:
            raise HTTPException(status_code=404, detail="Purchase not found")

        account = self.db.execute(
            text(
                """
                select id
                from accounts
                where id = :account_id and company_id = :company_id and is_active = true
                """
            ),
            {"account_id": str(payload.account_id), "company_id": resolved_company_id},
        ).scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        current_paid = Decimal(str(purchase["amount_paid"]))
        total = Decimal(str(purchase["total"]))
        new_amount_paid = current_paid + Decimal(str(payload.amount))
        if new_amount_paid - total > Decimal("0.0001"):
            raise HTTPException(status_code=422, detail="payment exceeds remaining balance")

        existing = self.db.execute(
            text(
                """
                select id
                from purchase_payments
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
            raise HTTPException(status_code=409, detail="Duplicate payment submission detected")

        payment_date = payload.payment_date or date.today()
        assert_period_open(
            db=self.db,
            company_id=resolved_company_id,
            transaction_date=payment_date,
            action_label="Posting purchase payment",
        )
        payment = self.db.execute(
            text(
                """
                insert into purchase_payments (
                    purchase_id,
                    company_id,
                    account_id,
                    amount,
                    payment_mode,
                    idempotency_key,
                    reference,
                    payment_date,
                    notes
                ) values (
                    :purchase_id,
                    :company_id,
                    :account_id,
                    :amount,
                    :payment_mode,
                    :idempotency_key,
                    :reference,
                    :payment_date,
                    :notes
                )
                returning id
                """
            ),
            {
                "purchase_id": purchase_id,
                "company_id": resolved_company_id,
                "account_id": str(payload.account_id),
                "amount": payload.amount,
                "payment_mode": payment_mode,
                "idempotency_key": payload.idempotency_key,
                "reference": payload.reference,
                "payment_date": payment_date,
                "notes": payload.notes,
            },
        ).mappings().first()

        if not payment:
            raise HTTPException(status_code=500, detail="Failed to create purchase payment")

        self.db.execute(
            text(
                """
                update purchases
                set
                    payment_mode = :payment_mode,
                    account_id = :account_id,
                    reference = coalesce(:reference, reference),
                    notes = coalesce(:notes, notes)
                where id = :purchase_id and company_id = :company_id
                """
            ),
            {
                "payment_mode": payment_mode,
                "account_id": str(payload.account_id),
                "reference": payload.reference,
                "notes": payload.notes,
                "purchase_id": purchase_id,
                "company_id": resolved_company_id,
            },
        )

        self._sync_purchase_payment_summary(
            purchase_id=purchase_id,
            company_id=resolved_company_id,
        )

        self.db.execute(
            text(
                """
                insert into account_transactions (
                    company_id,
                    from_account_id,
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
                    :amount,
                    :payment_mode,
                    :reference,
                    'purchase_payment',
                    :description,
                    :transaction_date,
                    'purchase_payment',
                    :source_id
                )
                """
            ),
            {
                "company_id": resolved_company_id,
                "from_account_id": str(payload.account_id),
                "amount": payload.amount,
                    "payment_mode": payment_mode,
                "reference": payload.reference,
                "description": payload.notes or "Purchase payment",
                    "transaction_date": payment_date,
                    "source_id": str(payment["id"]),
            },
        )

        self.db.commit()

        result = self.db.execute(
            text(
                """
                select
                    p.id,
                    p.company_id,
                    p.vendor_party_id,
                    v.legal_name as vendor_name,
                    p.bill_number,
                    p.purchase_date,
                    p.subtotal,
                    p.gst_total,
                    p.total,
                    p.amount_paid,
                    greatest(p.total - p.amount_paid, 0) as balance_amount,
                    p.payment_status,
                    p.payment_mode,
                    p.account_id,
                    p.reference,
                    p.due_date,
                    p.notes,
                    p.receipt_type,
                    p.receipt_status,
                    p.received_at,
                    p.received_notes,
                    p.status,
                    p.created_at
                from purchases p
                join parties v on v.id = p.vendor_party_id
                where p.id = :purchase_id and p.company_id = :company_id
                """
            ),
            {"purchase_id": purchase_id, "company_id": resolved_company_id},
        ).mappings().first()

        if not result:
            raise HTTPException(status_code=500, detail="Failed to load updated purchase")
        return dict(result)

    def list_purchase_payments(self, purchase_id: str, company_id: str | None) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        purchase = self.db.execute(
            text(
                """
                select id
                from purchases
                where id = :purchase_id and company_id = :company_id
                """
            ),
            {
                "purchase_id": purchase_id,
                "company_id": resolved_company_id,
            },
        ).scalar_one_or_none()
        if not purchase:
            raise HTTPException(status_code=404, detail="Purchase not found")

        rows = self.db.execute(
            text(
                """
                select
                    id,
                    purchase_id,
                    company_id,
                    account_id,
                    amount,
                    payment_mode,
                    idempotency_key,
                    reference,
                    payment_date,
                    notes,
                    reversed_at,
                    reversed_by_transaction_id,
                    created_at
                from purchase_payments
                where purchase_id = :purchase_id and company_id = :company_id
                order by payment_date desc, created_at desc
                """
            ),
            {
                "purchase_id": purchase_id,
                "company_id": resolved_company_id,
            },
        ).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def confirm_purchase_receipt(
        self,
        purchase_id: str,
        company_id: str | None,
        payload: PurchaseReceiptConfirm,
    ) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        purchase = self.db.execute(
            text(
                """
                select id, receipt_status
                from purchases
                where id = :purchase_id and company_id = :company_id
                """
            ),
            {"purchase_id": purchase_id, "company_id": resolved_company_id},
        ).mappings().first()
        if not purchase:
            raise HTTPException(status_code=404, detail="Purchase not found")

        receipt_type = self._normalize_receipt_type(payload.receipt_type)

        self.db.execute(
            text(
                """
                update purchases
                set
                    receipt_type = :receipt_type,
                    receipt_status = 'RECEIVED',
                    received_at = coalesce(:received_at, now()),
                    received_notes = :received_notes
                where id = :purchase_id and company_id = :company_id
                """
            ),
            {
                "receipt_type": receipt_type,
                "received_at": payload.received_at,
                "received_notes": payload.received_notes,
                "purchase_id": purchase_id,
                "company_id": resolved_company_id,
            },
        )
        self.db.commit()

        result = self.db.execute(
            text(
                """
                select
                    p.id,
                    p.company_id,
                    p.vendor_party_id,
                    v.legal_name as vendor_name,
                    p.bill_number,
                    p.purchase_date,
                    p.subtotal,
                    p.gst_total,
                    p.total,
                    p.amount_paid,
                    greatest(p.total - p.amount_paid, 0) as balance_amount,
                    p.payment_status,
                    p.payment_mode,
                    p.account_id,
                    p.reference,
                    p.due_date,
                    p.notes,
                    p.receipt_type,
                    p.receipt_status,
                    p.received_at,
                    p.received_notes,
                    p.status,
                    p.created_at
                from purchases p
                join parties v on v.id = p.vendor_party_id
                where p.id = :purchase_id and p.company_id = :company_id
                """
            ),
            {"purchase_id": purchase_id, "company_id": resolved_company_id},
        ).mappings().first()
        if not result:
            raise HTTPException(status_code=500, detail="Failed to load updated purchase")
        return dict(result)

    def export_purchase_register_csv(
        self,
        company_id: str | None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> str:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        try:
            from_value = date.fromisoformat(from_date) if from_date else date.today().replace(day=1)
            to_value = date.fromisoformat(to_date) if to_date else date.today()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="from_date/to_date must be YYYY-MM-DD") from exc
        if from_value > to_value:
            raise HTTPException(status_code=422, detail="from_date cannot be after to_date")

        company_gst = self.db.execute(
            text("select gst_number from companies where id = :company_id"),
            {"company_id": resolved_company_id},
        ).scalar_one_or_none()
        company_state = (str(company_gst)[:2] if company_gst else "")

        rows = self.db.execute(
            text(
                """
                select
                    p.bill_number,
                    p.purchase_date,
                    v.legal_name as vendor_name,
                    v.gst_number as vendor_gst,
                    p.subtotal,
                    p.gst_total,
                    p.total,
                    p.amount_paid,
                    greatest(p.total - p.amount_paid, 0) as balance_amount,
                    p.payment_status,
                    p.reference
                from purchases p
                join parties v on v.id = p.vendor_party_id
                where p.company_id = :company_id
                  and p.purchase_date between :from_date and :to_date
                order by p.purchase_date asc, p.created_at asc
                """
            ),
            {
                "company_id": resolved_company_id,
                "from_date": from_value,
                "to_date": to_value,
            },
        ).mappings().all()

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "bill_number",
                "purchase_date",
                "vendor_name",
                "vendor_gst",
                "taxable_value",
                "gst_total",
                "cgst",
                "sgst",
                "igst",
                "bill_total",
                "amount_paid",
                "balance_amount",
                "payment_status",
                "reference",
                "supply_type",
            ]
        )

        for row in rows:
            gst_total = Decimal(str(row["gst_total"] or 0))
            vendor_gst = str(row["vendor_gst"] or "")
            vendor_state = vendor_gst[:2] if vendor_gst else ""
            is_intra = bool(company_state and vendor_state and company_state == vendor_state)

            if is_intra:
                cgst = (gst_total / Decimal("2")).quantize(Decimal("0.01"))
                sgst = (gst_total - cgst).quantize(Decimal("0.01"))
                igst = Decimal("0.00")
                supply_type = "INTRA_STATE"
            else:
                cgst = Decimal("0.00")
                sgst = Decimal("0.00")
                igst = gst_total.quantize(Decimal("0.01"))
                supply_type = "INTER_STATE_OR_UNKNOWN"

            writer.writerow(
                [
                    row["bill_number"] or "",
                    row["purchase_date"],
                    row["vendor_name"],
                    row["vendor_gst"] or "",
                    row["subtotal"],
                    row["gst_total"],
                    cgst,
                    sgst,
                    igst,
                    row["total"],
                    row["amount_paid"],
                    row["balance_amount"],
                    row["payment_status"],
                    row["reference"] or "",
                    supply_type,
                ]
            )
        return output.getvalue()

    def export_ap_aging_csv(self, company_id: str | None, as_of: str | None = None) -> str:
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
                    p.id,
                    v.legal_name as vendor_name,
                    p.bill_number,
                    p.purchase_date,
                    p.due_date,
                    p.total,
                    p.amount_paid,
                    greatest(p.total - p.amount_paid, 0) as balance_amount
                from purchases p
                join parties v on v.id = p.vendor_party_id
                where p.company_id = :company_id
                  and greatest(p.total - p.amount_paid, 0) > 0
                order by coalesce(p.due_date, p.purchase_date) asc, p.created_at asc
                """
            ),
            {"company_id": resolved_company_id},
        ).mappings().all()

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "vendor_name",
                "bill_number",
                "purchase_date",
                "due_date",
                "balance_amount",
                "age_days",
                "bucket",
            ]
        )

        for row in rows:
            due_base = row["due_date"] or row["purchase_date"]
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
                    row["vendor_name"],
                    row["bill_number"] or "",
                    row["purchase_date"],
                    row["due_date"] or "",
                    row["balance_amount"],
                    age_days,
                    bucket,
                ]
            )
        return output.getvalue()
