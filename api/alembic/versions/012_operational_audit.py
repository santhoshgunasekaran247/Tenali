"""Capture future operational changes without storing receipt bytes or signature images."""

from alembic import op

revision="012_operational_audit"
down_revision="011_document_cancellation"
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""
        create table if not exists purchase_payments (
            id uuid primary key default gen_random_uuid(), purchase_id uuid not null references purchases(id),
            company_id uuid not null references companies(id), account_id uuid references accounts(id),
            amount numeric(14,2) not null check(amount>0),payment_mode text not null,idempotency_key text,
            reference text,payment_date date not null default current_date,notes text,reversed_at timestamptz,
            reversed_by_transaction_id uuid references account_transactions(id),created_by uuid references user_profiles(id),
            created_at timestamptz not null default now()
        );
        create table if not exists receivable_payments (
            id uuid primary key default gen_random_uuid(),receivable_id uuid not null references receivables(id),
            company_id uuid not null references companies(id),account_id uuid references accounts(id),
            amount numeric(14,2) not null check(amount>0),payment_mode text not null,idempotency_key text,
            reference text,payment_date date not null default current_date,notes text,reversed_at timestamptz,
            reversed_by_transaction_id uuid references account_transactions(id),created_by uuid references user_profiles(id),
            created_at timestamptz not null default now()
        );
        create or replace function tenali_operational_audit() returns trigger language plpgsql as $$
        declare old_payload jsonb; new_payload jsonb; record_payload jsonb; owner_id uuid;
        begin
            old_payload := case when TG_OP='INSERT' then null else to_jsonb(OLD) end;
            new_payload := case when TG_OP='DELETE' then null else to_jsonb(NEW) end;
            record_payload := coalesce(new_payload,old_payload);
            owner_id := nullif(record_payload->>'company_id','')::uuid;
            if TG_TABLE_NAME='companies' then owner_id := (record_payload->>'id')::uuid; end if;
            if owner_id is null and record_payload ? 'product_id' then
                select company_id into owner_id from products where id=(record_payload->>'product_id')::uuid;
            end if;
            old_payload := old_payload - 'file_content' - 'document_data' - 'line_items' - 'logo_url' - 'invoice_settings';
            new_payload := new_payload - 'file_content' - 'document_data' - 'line_items' - 'logo_url' - 'invoice_settings';
            insert into audit_events(company_id,action,entity_type,entity_id,old_value,new_value,source_type)
            values(owner_id,TG_OP,TG_TABLE_NAME,(record_payload->>'id')::uuid,old_payload,new_payload,'database');
            return null;
        end $$;
        do $$ declare table_name text;
        begin
            foreach table_name in array array['companies','parties','products','product_variants','vendor_contributions',
                'stock_movements','invoices','purchases','account_transactions','receivable_payments','purchase_payments','hsn_masters','documents','brands','product_categories','receivables']
            loop
                if to_regclass(table_name) is null then continue; end if;
                execute format('drop trigger if exists tenali_audit_change on %I',table_name);
                execute format('create trigger tenali_audit_change after insert or update or delete on %I for each row execute function tenali_operational_audit()',table_name);
            end loop;
        end $$;
    """)


def downgrade():
    raise NotImplementedError("Audit history must be retained")