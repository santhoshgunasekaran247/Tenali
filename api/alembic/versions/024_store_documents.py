"""Finance documents and transactions belong to a store; per-store document numbering starts fresh."""

from alembic import op

revision = "024_store_documents"
down_revision = "023_stock_per_store"
branch_labels = None
depends_on = None

STORE_TABLES = (
    "invoices", "purchases", "receivables", "receivable_payments", "purchase_payments",
    "account_transactions", "borrowings",
)


def upgrade():
    statements = []
    for table in STORE_TABLES:
        statements.append(f"alter table {table} add column if not exists store_id uuid references stores(id);")
        statements.append(
            f"update {table} t set store_id = s.id from stores s "
            f"where s.company_id = t.company_id and s.is_default and t.store_id is null;"
        )
        statements.append(f"alter table {table} alter column store_id set not null;")
        statements.append(f"create index if not exists ix_{table}_store on {table}(company_id, store_id);")
    op.execute("\n".join(statements))
    op.execute(
        """
        alter table accounting_period_locks add column if not exists store_id uuid references stores(id);
        alter table accounts add column if not exists store_id uuid references stores(id);
        alter table purchases add column if not exists voucher_number text;
        create unique index if not exists uq_purchases_voucher on purchases(company_id, voucher_number)
            where voucher_number is not null;

        create table document_sequences (
            company_id uuid not null references companies(id),
            store_id uuid not null references stores(id),
            kind text not null check (kind in ('invoice','purchase')),
            year integer not null,
            month integer not null check (month between 1 and 12),
            last_number integer not null default 0,
            primary key (company_id, store_id, kind, year, month)
        );
        alter table document_sequences enable row level security;
        create policy tenali_company_scope on document_sequences to tenali_runtime
            using (company_id = tenali_current_company()) with check (company_id = tenali_current_company());
        grant select, insert, update on document_sequences to tenali_runtime;
        create trigger tenali_company_relationship before insert or update on document_sequences
            for each row execute function tenali_guard_relationships();

        drop table if exists invoice_sequences;

        create or replace function tenali_default_store() returns trigger language plpgsql as $$
        declare payload jsonb; parent uuid; source_type text;
        begin
            if NEW.store_id is not null then return NEW; end if;
            payload := to_jsonb(NEW);
            if TG_TABLE_NAME = 'receivables' and payload->>'invoice_id' is not null then
                select store_id into NEW.store_id from invoices where id = (payload->>'invoice_id')::uuid;
            elsif TG_TABLE_NAME = 'receivable_payments' then
                select store_id into NEW.store_id from receivables where id = (payload->>'receivable_id')::uuid;
            elsif TG_TABLE_NAME = 'purchase_payments' then
                select store_id into NEW.store_id from purchases where id = (payload->>'purchase_id')::uuid;
            elsif TG_TABLE_NAME = 'borrowings' and payload->>'source_transaction_id' is not null then
                select store_id into NEW.store_id from account_transactions where id = (payload->>'source_transaction_id')::uuid;
            elsif TG_TABLE_NAME = 'account_transactions' then
                source_type := payload->>'source_type';
                parent := nullif(payload->>'source_id', '')::uuid;
                if payload->>'reversal_of_transaction_id' is not null then
                    select store_id into NEW.store_id from account_transactions where id = (payload->>'reversal_of_transaction_id')::uuid;
                elsif source_type = 'invoice' then select store_id into NEW.store_id from invoices where id = parent;
                elsif source_type = 'purchase' then select store_id into NEW.store_id from purchases where id = parent;
                elsif source_type = 'receivable_payment' then select store_id into NEW.store_id from receivable_payments where id = parent;
                elsif source_type = 'purchase_payment' then select store_id into NEW.store_id from purchase_payments where id = parent;
                elsif source_type = 'borrowing' then select store_id into NEW.store_id from borrowings where id = parent;
                elsif source_type = 'shop_order' then select store_id into NEW.store_id from shop_orders where id = parent;
                end if;
            end if;
            if NEW.store_id is null then
                select id into NEW.store_id from stores where company_id = NEW.company_id and is_default;
            end if;
            return NEW;
        end $$;
        do $$ declare table_name text;
        begin
            foreach table_name in array array['invoices','purchases','receivables','receivable_payments',
                'purchase_payments','account_transactions','borrowings'] loop
                execute format('create trigger tenali_default_store before insert on %I for each row execute function tenali_default_store()', table_name);
            end loop;
        end $$;
        """
    )


def downgrade():
    raise NotImplementedError("Store attribution and fresh numbering cannot be reversed safely")
