"""Reviewed transaction deletion: every delete runs inside a recorded batch and every removed row is archived.

Ledger tables stay append-only for ordinary requests. Delete rights are granted to the runtime role, but a
BEFORE DELETE trigger refuses any delete that is not part of a deletion batch opened in the same database
transaction, and copies the full row (including invoice/purchase line data) into deleted_records.
"""
from alembic import op

revision = "038_transaction_deletions"
down_revision = "037_product_drafts"
branch_labels = None
depends_on = None

GUARDED = (
    "account_transactions", "stock_movements", "invoices", "invoice_items", "purchases", "purchase_items",
    "purchase_payments", "receivables", "receivable_payments", "receivable_reminders", "expenses", "settlements",
    "borrowings", "salary_transactions", "shop_orders", "stock_transfers", "document_links", "posting_requests",
    "cod_settlements", "cod_settlement_items", "invoice_reconcile_runs",
)
ARCHIVED = ("stock_balances",)


def upgrade():
    op.execute("""
        create table transaction_deletions (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            kind text not null,
            root_id uuid,
            label text not null,
            reason text not null check (length(btrim(reason)) between 1 and 1000),
            summary jsonb not null,
            deleted_by uuid,
            txid bigint not null default txid_current(),
            deleted_at timestamptz not null default now()
        );
        create index idx_transaction_deletions_company on transaction_deletions(company_id, deleted_at desc);
        create table deleted_records (
            id uuid primary key default gen_random_uuid(),
            deletion_id uuid not null references transaction_deletions(id),
            company_id uuid not null references companies(id),
            entity_type text not null,
            entity_id uuid,
            payload jsonb not null,
            deleted_at timestamptz not null default now()
        );
        create index idx_deleted_records_deletion on deleted_records(deletion_id);
        create index idx_deleted_records_entity on deleted_records(company_id, entity_type, entity_id);
        alter table transaction_deletions enable row level security;
        alter table deleted_records enable row level security;
        create policy tenali_company_scope on transaction_deletions to tenali_runtime
            using (company_id = tenali_current_company()) with check (company_id = tenali_current_company());
        create policy tenali_company_scope on deleted_records to tenali_runtime
            using (company_id = tenali_current_company()) with check (company_id = tenali_current_company());
        grant select, insert on transaction_deletions to tenali_runtime;
        grant select on deleted_records to tenali_runtime;

        create or replace function tenali_transaction_delete() returns trigger
        language plpgsql security definer set search_path = public, pg_temp as $$
        declare batch uuid; batch_company uuid; row_company uuid; payload jsonb := to_jsonb(OLD);
        begin
            batch := nullif(current_setting('app.deletion_batch', true), '')::uuid;
            if batch is not null then
                select company_id into batch_company from transaction_deletions
                where id = batch and txid = txid_current();
            end if;
            if batch_company is null then
                if TG_ARGV[0] = 'guard' then
                    raise exception 'Transactions can only be deleted through a reviewed deletion' using errcode = '42501';
                end if;
                return OLD;
            end if;
            row_company := nullif(payload->>'company_id', '')::uuid;
            if row_company is not null and row_company <> batch_company then
                raise exception 'Deletion batch belongs to another workspace' using errcode = '42501';
            end if;
            insert into deleted_records(deletion_id, company_id, entity_type, entity_id, payload)
            values (batch, batch_company, TG_TABLE_NAME, nullif(payload->>'id', '')::uuid, payload);
            return OLD;
        end $$;
        revoke all on function tenali_transaction_delete() from public;
    """)
    for table in GUARDED:
        op.execute(f"""create trigger tenali_transaction_delete before delete on {table}
            for each row execute function tenali_transaction_delete('guard');
            grant delete on {table} to tenali_runtime;""")
    for table in ARCHIVED:
        op.execute(f"""create trigger tenali_transaction_delete before delete on {table}
            for each row execute function tenali_transaction_delete('archive');""")


def downgrade():
    raise NotImplementedError("Deletion archives and their guard must be preserved")
