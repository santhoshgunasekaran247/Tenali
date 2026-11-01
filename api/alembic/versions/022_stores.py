"""Stores master: every company gets a default store; online shopper party; pricing flag."""

from alembic import op

revision = "022_stores"
down_revision = "021_unique_invoice_receivable"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        alter table companies add column if not exists prices_include_gst boolean not null default true;
        alter table companies add column if not exists whatsapp_number text;
        alter table parties add column if not exists system_role text
            check (system_role is null or system_role in ('online_shopper'));
        create unique index if not exists uq_parties_system_role
            on parties(company_id, system_role) where system_role is not null;

        create table stores (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            code text not null check (code ~ '^[A-Z0-9]{2,8}$'),
            name text not null check (length(trim(name)) between 1 and 120),
            kind text not null check (kind in ('offline','warehouse','online')),
            holds_stock boolean not null,
            fulfilment_store_id uuid references stores(id),
            allows_pickup boolean not null default false,
            address text,
            state_code char(2) check (state_code is null or state_code ~ '^[0-9]{2}$'),
            pincode text check (pincode is null or pincode ~ '^[1-9][0-9]{5}$'),
            latitude numeric(9,6) check (latitude is null or latitude between -90 and 90),
            longitude numeric(9,6) check (longitude is null or longitude between -180 and 180),
            gst_number text check (gst_number is null or gst_number ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
            whatsapp_number text check (whatsapp_number is null or whatsapp_number ~ '^\\+[1-9][0-9]{7,14}$'),
            settlement_account_id uuid references accounts(id),
            is_default boolean not null default false,
            is_active boolean not null default true,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (company_id, code),
            unique (company_id, id),
            check ((kind = 'online') = (holds_stock = false)),
            check (kind <> 'online' or fulfilment_store_id is not null),
            check (kind = 'online' or fulfilment_store_id is null),
            check (kind <> 'online' or allows_pickup = false),
            check (not is_default or kind <> 'online')
        );
        create unique index uq_stores_default on stores(company_id) where is_default;
        create index ix_stores_company_active on stores(company_id, is_active, kind);

        alter table stores enable row level security;
        create policy tenali_company_scope on stores to tenali_runtime
            using (company_id = tenali_current_company()) with check (company_id = tenali_current_company());
        grant select, insert, update on stores to tenali_runtime;
        create trigger tenali_company_relationship before insert or update on stores
            for each row execute function tenali_guard_relationships();
        create trigger tenali_audit_change after insert or update or delete on stores
            for each row execute function tenali_operational_audit();

        insert into stores (company_id, code, name, kind, holds_stock, address, is_default)
        select c.id, 'MAIN', 'Main store', 'offline', true, c.address, true
        from companies c
        where not exists (select 1 from stores s where s.company_id = c.id and s.is_default);

        insert into parties (company_id, party_type, legal_name, system_role)
        select c.id, 'customer', 'Online shopper', 'online_shopper'
        from companies c
        where not exists (select 1 from parties p where p.company_id = c.id and p.system_role = 'online_shopper');
        """
    )


def downgrade():
    op.execute(
        """
        drop table stores;
        drop index if exists uq_parties_system_role;
        alter table parties drop column if exists system_role;
        alter table companies drop column if exists whatsapp_number;
        alter table companies drop column if exists prices_include_gst;
        """
    )
