from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from io import StringIO

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.billing import InvoiceCreate
from app.services.collection_ledger import lock_invoice_receivables, sync_receivable
from app.services.document_numbers import next_document_number
from app.services.financial_amounts import document_total
from app.services.period_lock_service import assert_period_open
from app.services.invoice_document import build_invoice_document
from app.services.masters_service import MastersService
from app.services.commerce_stock import resolve_product_lines, book_stock
from app.services.posting_service import replay_posting, finish_posting, request_hash
from app.services.runtime_schema import managed_schema
from app.services.access import allowed_stores
from app.services.stores_service import get_store, stock_store


class BillingService:
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
        if managed_schema(self.db): return
        self.db.execute(
            text(
                """
                create table if not exists invoices (
                    id uuid primary key default gen_random_uuid(),
                    company_id uuid not null references companies(id),
                    invoice_number text not null,
                    customer_party_id uuid not null references parties(id),
                    customer_gst text,
                    invoice_date date not null default current_date,
                    subtotal numeric(14,2) not null default 0,
                    gst_total numeric(14,2) not null default 0,
                    total numeric(14,2) not null default 0,
                    payment_mode text,
                    account_id uuid references accounts(id),
                    reference text,
                    status text not null default 'POSTED',
                    collection_status text not null default 'UNPAID' check (collection_status in ('UNPAID','PARTIAL','SETTLED','BAD_DEBT')),
                    amount_received numeric(14,2) not null default 0,
                    due_date date,
                    reminder_date date,
                    bad_debt_reason text,
                    created_by uuid references user_profiles(id),
                    created_at timestamptz not null default now(),
                    unique(company_id, invoice_number)
                )
                """
            )
        )
        self.db.execute(
            text(
                "alter table invoices add column if not exists collection_status text not null default 'UNPAID'"
            )
        )
        self.db.execute(
            text("alter table invoices add column if not exists amount_received numeric(14,2) not null default 0")
        )
        self.db.execute(text("alter table invoices add column if not exists due_date date"))
        self.db.execute(text("alter table invoices add column if not exists reminder_date date"))
        self.db.execute(text("alter table invoices add column if not exists bad_debt_reason text"))
        self.db.execute(text("alter table invoices add column if not exists document_data jsonb"))
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
                create table if not exists invoice_sequences (
                    id uuid primary key default gen_random_uuid(),
                    company_id uuid not null references companies(id),
                    year integer not null,
                    month integer not null,
                    last_number integer not null default 0,
                    unique(company_id, year, month)
                )
                """
            )
        )
        self.db.execute(
            text(
                """
                create table if not exists invoice_reconcile_runs (
                    id uuid primary key default gen_random_uuid(),
                    company_id uuid not null references companies(id),
                    healed_count integer not null default 0,
                    triggered_by text,
                    created_at timestamptz not null default now()
                )
                """
            )
        )
        self.db.execute(
            text(
                "create index if not exists idx_invoice_reconcile_runs_company_date on invoice_reconcile_runs(company_id, created_at desc)"
            )
        )

    def _new_invoice_number(self, company_id: str, store: dict, invoice_date: date) -> str:
        return next_document_number(self.db, company_id, store, "invoice", invoice_date)

    def _reconcile_invoice_collection_fields(self, company_id: str) -> int:
        invoice_ids = self.db.execute(
            text(
                """
                select distinct r.invoice_id
                from receivables r
                join invoices i on i.id = r.invoice_id and i.company_id = r.company_id
                where r.company_id = :company_id and i.status <> 'CANCELLED'
                order by r.invoice_id
                """
            ),
            {"company_id": company_id},
        ).scalars().all()
        healed_count = 0
        for invoice_id in invoice_ids:
            invoice, receivable = lock_invoice_receivables(self.db, company_id, str(invoice_id))
            if receivable and invoice["status"] != "CANCELLED":
                _, _, changed = sync_receivable(self.db, company_id, receivable, invoice)
                healed_count += int(changed)
        return healed_count

    def reconcile_invoices(self, company_id: str | None, triggered_by: str | None = None) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)
        healed_count = self._reconcile_invoice_collection_fields(company_id=resolved_company_id)
        self.db.execute(
            text(
                """
                insert into invoice_reconcile_runs (
                    company_id,
                    healed_count,
                    triggered_by
                ) values (
                    :company_id,
                    :healed_count,
                    :triggered_by
                )
                """
            ),
            {
                "company_id": resolved_company_id,
                "healed_count": healed_count,
                "triggered_by": triggered_by,
            },
        )
        self.db.commit()
        return {"healed_count": healed_count}

    def list_reconcile_runs(self, company_id: str | None, limit: int = 10, offset: int = 0) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)
        safe_limit = min(max(limit, 1), 100)
        safe_offset = max(offset, 0)

        total = self.db.execute(
            text(
                """
                select count(*)
                from invoice_reconcile_runs
                where company_id = :company_id
                """
            ),
            {"company_id": resolved_company_id},
        ).scalar_one()

        rows = self.db.execute(
            text(
                """
                select id, company_id, healed_count, triggered_by, created_at
                from invoice_reconcile_runs
                where company_id = :company_id
                order by created_at desc
                limit :limit
                offset :offset
                """
            ),
            {"company_id": resolved_company_id, "limit": safe_limit, "offset": safe_offset},
        ).mappings().all()
        return {
            "items": [dict(row) for row in rows],
            "total": int(total or 0),
            "limit": safe_limit,
            "offset": safe_offset,
        }

    def create_invoice(self, company_id: str | None, payload: InvoiceCreate) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)
        original_hash=request_hash(payload)
        cached=replay_posting(self.db,resolved_company_id,"invoice",payload)
        if cached is not None:
            return cached

        customer = self.db.execute(
            text(
                """
                select id, legal_name, gst_number, address
                from parties
                where id = :party_id and company_id = :company_id and is_active = true
                """
            ),
            {"party_id": str(payload.customer_party_id), "company_id": resolved_company_id},
        ).mappings().first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer party not found")
        store = get_store(self.db, resolved_company_id, str(payload.store_id) if payload.store_id else None)
        stock_store_id = str(payload.stock_store_id) if payload.stock_store_id else str(store["fulfilment_store_id"] or store["id"])
        if not stock_store(self.db, resolved_company_id, stock_store_id):
            raise HTTPException(422, "Stock store not found")

        document_data = None
        if payload.lines:
            resolve_product_lines(self.db,resolved_company_id,payload.lines)
            MastersService(self.db).apply_hsn_rates(payload.lines, resolved_company_id)
            company = self.db.execute(
                text("select company_name, address, gst_number, gst_registered, udyam_number, logo_url, phone, email, website, invoice_settings, prices_include_gst from companies where id = :company_id"),
                {"company_id": resolved_company_id},
            ).mappings().one()
            document_data = build_invoice_document(payload, dict(company), dict(customer), store, bool(company["prices_include_gst"]))
            payload.subtotal = Decimal(document_data["subtotal"])
            payload.gst_total = Decimal(document_data["gst_total"])
            payload.total = Decimal(document_data["total"])

        if payload.subtotal < 0 or payload.gst_total < 0:
            raise HTTPException(status_code=422, detail="subtotal and gst_total must be non-negative")

        total_amount = document_total(payload.subtotal, payload.gst_total, payload.total)
        total = total_amount
        amount_received = payload.amount_received
        if amount_received < Decimal("0"):
            raise HTTPException(status_code=422, detail="amount_received cannot be negative")
        if amount_received > total_amount:
            raise HTTPException(status_code=422, detail="amount_received cannot exceed total")

        if payload.amount_received > 0 and not (payload.payment_mode or "").strip():
            raise HTTPException(status_code=422, detail="payment_mode required when amount_received > 0")
        if payload.amount_received > 0 and not payload.account_id:
            raise HTTPException(status_code=422, detail="account_id required when amount_received > 0")

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

        balance = total_amount - amount_received
        if balance <= Decimal("0.0001"):
            collection_status = "SETTLED"
        elif amount_received > Decimal("0"):
            collection_status = "PARTIAL"
        else:
            collection_status = "UNPAID"

        invoice_date_value = payload.invoice_date or date.today()
        assert_period_open(
            db=self.db,
            company_id=resolved_company_id,
            transaction_date=invoice_date_value,
            action_label="Posting invoice",
        )

        invoice_row = self.db.execute(
            text(
                """
                insert into invoices (
                    company_id,
                    store_id,
                    invoice_number,
                    customer_party_id,
                    customer_gst,
                    invoice_date,
                    subtotal,
                    gst_total,
                    total,
                    payment_mode,
                    account_id,
                    reference,
                    status,
                    collection_status,
                    amount_received,
                    due_date,
                    reminder_date,
                    document_data
                ) values (
                    :company_id,
                    :store_id,
                    :invoice_number,
                    :customer_party_id,
                    :customer_gst,
                    :invoice_date,
                    :subtotal,
                    :gst_total,
                    :total,
                    :payment_mode,
                    :account_id,
                    :reference,
                    'POSTED',
                    :collection_status,
                    :amount_received,
                    :due_date,
                    :reminder_date,
                    cast(:document_data as jsonb)
                )
                returning
                    id,
                    company_id,
                    store_id,
                    invoice_number,
                    customer_party_id,
                    customer_gst,
                    invoice_date,
                    subtotal,
                    gst_total,
                    total,
                    payment_mode,
                    account_id,
                    reference,
                    status,
                    collection_status,
                    amount_received,
                    due_date,
                    reminder_date,
                    bad_debt_reason,
                    created_at
                """
            ),
            {
                "company_id": resolved_company_id,
                "store_id": str(store["id"]),
                "invoice_number": self._new_invoice_number(resolved_company_id, store, invoice_date_value),
                "customer_party_id": str(payload.customer_party_id),
                "customer_gst": customer["gst_number"],
                "invoice_date": invoice_date_value,
                "subtotal": payload.subtotal,
                "gst_total": payload.gst_total,
                "total": total,
                "payment_mode": payload.payment_mode.strip() if payload.payment_mode else None,
                "account_id": str(payload.account_id) if payload.account_id else None,
                "reference": payload.reference,
                "collection_status": collection_status,
                "amount_received": amount_received,
                "due_date": payload.due_date,
                "reminder_date": payload.reminder_date,
                "document_data": json.dumps(document_data) if document_data else None,
            },
        ).mappings().first()

        if not invoice_row:
            raise HTTPException(status_code=500, detail="Failed to create invoice")

        invoice_id = str(invoice_row["id"])

        if payload.auto_create_receivable:
            self.db.execute(
                text(
                    """
                    insert into receivables (
                        company_id,
                        party_id,
                        invoice_id,
                        reference,
                        amount_due,
                        amount_received,
                        status,
                        due_date,
                        reminder_date,
                        notes,
                        updated_at
                    ) values (
                        :company_id,
                        :party_id,
                        :invoice_id,
                        :reference,
                        :amount_due,
                        :amount_received,
                        :status,
                        :due_date,
                        :reminder_date,
                        :notes,
                        now()
                    )
                    """
                ),
                {
                    "company_id": resolved_company_id,
                    "party_id": str(payload.customer_party_id),
                    "invoice_id": invoice_id,
                    "reference": payload.reference or invoice_row["invoice_number"],
                    "amount_due": total,
                    "amount_received": amount_received,
                    "status": collection_status,
                    "due_date": payload.due_date,
                    "reminder_date": payload.reminder_date,
                    "notes": payload.notes,
                },
            )

        if amount_received > 0 and payload.account_id:
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
                        'sales_collection',
                        :description,
                        :transaction_date,
                        'invoice',
                        :source_id
                    )
                    """
                ),
                {
                    "company_id": resolved_company_id,
                    "to_account_id": str(payload.account_id),
                    "amount": amount_received,
                    "payment_mode": payload.payment_mode.strip() if payload.payment_mode else None,
                    "reference": payload.reference,
                    "description": f"Collection for {invoice_row['invoice_number']}",
                    "transaction_date": invoice_date_value,
                    "source_id": invoice_id,
                },
            )

        if document_data:
            book_stock(self.db,resolved_company_id,document_data["lines"],"OUT","invoice",invoice_id,stock_store_id)
        result = {
            **dict(invoice_row),
            "customer_name": customer["legal_name"],
            "document_data": document_data,
        }
        finish_posting(self.db,resolved_company_id,"invoice",payload,result,original_hash)
        self.db.commit()
        return result

    def list_invoices(self, company_id: str | None, collection_status: str | None = None, store_id: str | None = None) -> dict:
        self._ensure_tables()
        resolved_company_id = self._resolve_company_id(company_id)

        query = """
            select
                i.id,
                i.company_id,
                i.store_id,
                s.code as store_code,
                i.invoice_number,
                i.customer_party_id,
                p.legal_name as customer_name,
                i.customer_gst,
                i.invoice_date,
                i.subtotal,
                i.gst_total,
                i.total,
                i.payment_mode,
                i.account_id,
                i.reference,
                i.status,
                i.collection_status,
                i.amount_received,
                i.due_date,
                i.reminder_date,
                i.bad_debt_reason,
                i.document_data,
                i.cancelled_at,
                i.cancellation_reason,
                i.created_at
            from invoices i
            join parties p on p.id = i.customer_party_id
            left join stores s on s.id = i.store_id
            where i.company_id = :company_id
        """
        params: dict[str, object] = {"company_id": resolved_company_id}
        if store_id:
            query += " and i.store_id = :store_id"
            params["store_id"] = store_id
        permitted = allowed_stores(self.db.info.get("tenant_context"))
        if permitted is not None:
            query += " and i.store_id = any(cast(:permitted as uuid[]))"
            params["permitted"] = permitted

        if collection_status:
            normalized = collection_status.strip().upper()
            if normalized not in {"UNPAID", "PARTIAL", "SETTLED", "BAD_DEBT"}:
                raise HTTPException(status_code=422, detail="Invalid collection_status")
            query += " and i.collection_status = :collection_status"
            params["collection_status"] = normalized

        query += " order by i.invoice_date desc, i.created_at desc"
        rows = self.db.execute(text(query), params).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def export_sales_register_csv(
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
            text(
                """
                select gst_number
                from companies
                where id = :company_id
                """
            ),
            {"company_id": resolved_company_id},
        ).scalar_one_or_none()
        company_state = (str(company_gst)[:2] if company_gst else "")

        rows = self.db.execute(
            text(
                """
                select
                    i.invoice_number,
                    i.invoice_date,
                    p.legal_name as customer_name,
                    i.customer_gst as customer_gst,
                    i.subtotal,
                    i.gst_total,
                    i.total,
                    i.amount_received,
                    i.collection_status,
                    i.reference,i.document_data,i.status,i.cancelled_at
                from invoices i
                join parties p on p.id = i.customer_party_id
                where i.company_id = :company_id
                  and i.invoice_date between :from_date and :to_date
                order by i.invoice_date asc, i.invoice_number asc
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
                "invoice_number",
                "invoice_date",
                "customer_name",
                "customer_gst",
                "taxable_value",
                "gst_total",
                "cgst",
                "sgst",
                "igst",
                "invoice_total",
                "amount_received",
                "collection_status",
                "reference",
                "supply_type",
                "document_status","cancelled_at",
            ]
        )

        for row in rows:
            gst_total = Decimal(str(row["gst_total"] or 0))
            customer_gst = str(row["customer_gst"] or "")
            customer_state = customer_gst[:2] if customer_gst else ""
            snapshot=row["document_data"] or {}
            seller_state=str(snapshot.get("seller",{}).get("gst_number") or company_gst or "")[:2]
            supply_state=str(snapshot.get("place_of_supply") or customer_state)[:2]
            is_intra = bool(seller_state and supply_state and seller_state == supply_state)

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

            if snapshot.get("lines"):
                cgst=sum((Decimal(str(line.get("cgst",0))) for line in snapshot["lines"]),Decimal('0'))
                sgst=sum((Decimal(str(line.get("sgst",0))) for line in snapshot["lines"]),Decimal('0'))
                igst=sum((Decimal(str(line.get("igst",0))) for line in snapshot["lines"]),Decimal('0'))

            writer.writerow(
                [
                    row["invoice_number"],
                    row["invoice_date"],
                    row["customer_name"],
                    row["customer_gst"] or "",
                    row["subtotal"],
                    row["gst_total"],
                    cgst,
                    sgst,
                    igst,
                    row["total"],
                    row["amount_received"],
                    row["collection_status"],
                    row["reference"] or "",
                    supply_type,
                    row["status"],row["cancelled_at"] or "",
                ]
            )

        return output.getvalue()
