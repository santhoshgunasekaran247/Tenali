"""Online channel: order modes, enquiries, COD settlements and checkout policy settings."""

from alembic import op

revision = "025_online_channel"
down_revision = "024_store_documents"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        alter table shop_orders
            add column if not exists store_id uuid references stores(id),
            add column if not exists channel text not null default 'web'
                check (channel in ('web','whatsapp')),
            add column if not exists payment_method text not null default 'prepaid'
                check (payment_method in ('prepaid','cod','pay_at_pickup')),
            add column if not exists fulfilment_method text not null default 'delivery'
                check (fulfilment_method in ('delivery','pickup')),
            add column if not exists pickup_store_id uuid references stores(id),
            add column if not exists ship_from_store_id uuid references stores(id),
            add column if not exists invoice_id uuid references invoices(id),
            add column if not exists advance_transaction_id uuid references account_transactions(id),
            add column if not exists expires_at timestamptz,
            add column if not exists approved_by uuid,
            add column if not exists approved_at timestamptz,
            add column if not exists decline_reason text,
            add column if not exists dispatched_at timestamptz,
            add column if not exists delivered_at timestamptz,
            add column if not exists ready_at timestamptz,
            add column if not exists collected_at timestamptz,
            add column if not exists cancelled_at timestamptz,
            add column if not exists cancellation_reason text,
            add column if not exists review_reason text;
        alter table shop_orders alter column provider_key_id drop not null;
        alter table shop_orders alter column credentials drop not null;
        create unique index if not exists uq_shop_orders_invoice on shop_orders(company_id, invoice_id)
            where invoice_id is not null;
        create unique index if not exists uq_shop_orders_advance on shop_orders(company_id, advance_transaction_id)
            where advance_transaction_id is not null;

        do $$ declare constraint_name text;
        begin
            for constraint_name in
                select conname from pg_constraint
                where conrelid = 'shop_orders'::regclass and contype = 'c'
                  and pg_get_constraintdef(oid) like '%awaiting_payment%'
            loop
                execute format('alter table shop_orders drop constraint %I', constraint_name);
            end loop;
        end $$;
        update shop_orders set status = 'fulfilment_review', review_reason = 'Stock review required at payment capture'
            where status = 'payment_review';
        alter table shop_orders add constraint shop_orders_status_check check (status in (
            'awaiting_payment','paid','cod_requested','confirmed','fulfilment_review',
            'shipping_pending','shipment_booked','dispatched','delivered',
            'ready_for_pickup','collected','expired','cancelled','refunded'));
        alter table shop_orders add constraint shop_orders_pickup_store_check
            check (fulfilment_method <> 'pickup' or pickup_store_id is not null);
        create index if not exists ix_shop_orders_expiry on shop_orders(company_id, expires_at)
            where expires_at is not null and status in ('awaiting_payment','cod_requested','confirmed');

        alter table checkout_settings
            add column if not exists prepaid_enabled boolean not null default true,
            add column if not exists shipping_sac text not null default '9968',
            add column if not exists shipping_gst_rate numeric(5,2) not null default 18
                check (shipping_gst_rate between 0 and 100),
            add column if not exists cod_enabled boolean not null default false,
            add column if not exists cod_limit numeric(14,2) not null default 5000 check (cod_limit >= 0),
            add column if not exists cod_approval_hours integer not null default 24 check (cod_approval_hours between 1 and 720),
            add column if not exists cod_overdue_days integer not null default 15 check (cod_overdue_days between 1 and 365),
            add column if not exists pickup_enabled boolean not null default false,
            add column if not exists pickup_hold_hours integer not null default 72 check (pickup_hold_hours between 1 and 720),
            add column if not exists pickup_reminder_hours integer not null default 48 check (pickup_reminder_hours between 1 and 720),
            add column if not exists prepaid_hold_minutes integer not null default 20 check (prepaid_hold_minutes between 5 and 180),
            add column if not exists cod_serviceable_pincodes text[] not null default '{}';
        alter table checkout_settings alter column credentials set default '';
        alter table checkout_settings alter column pickup_location set default '';

        create table enquiries (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            reference text not null,
            store_id uuid references stores(id),
            product_id uuid not null references products(id),
            variant_id uuid references product_variants(id),
            quantity numeric(14,3) not null check (quantity > 0),
            shopper_name text not null check (length(trim(shopper_name)) between 1 and 120),
            shopper_phone text not null check (shopper_phone ~ '^\\+[1-9][0-9]{7,14}$'),
            message text check (message is null or length(message) <= 1000),
            status text not null default 'open' check (status in ('open','quoted','converted','closed')),
            invoice_id uuid references invoices(id),
            handled_by uuid,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (company_id, reference)
        );
        create index ix_enquiries_company_status on enquiries(company_id, status, created_at desc);

        create table cod_settlements (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            courier text not null check (length(trim(courier)) between 1 and 80),
            settlement_reference text not null check (length(trim(settlement_reference)) between 1 and 120),
            settlement_date date not null,
            account_id uuid not null references accounts(id),
            expected_amount numeric(14,2) not null check (expected_amount >= 0),
            received_amount numeric(14,2) not null check (received_amount >= 0),
            shortfall_reason text,
            notes text,
            created_by uuid,
            created_at timestamptz not null default now(),
            unique (company_id, courier, settlement_reference),
            check (received_amount >= expected_amount or shortfall_reason is not null)
        );
        create table cod_settlement_items (
            settlement_id uuid not null references cod_settlements(id),
            company_id uuid not null references companies(id),
            order_id uuid not null references shop_orders(id),
            invoice_id uuid not null references invoices(id),
            amount numeric(14,2) not null check (amount > 0),
            primary key (settlement_id, order_id)
        );
        create unique index uq_cod_settlement_items_order on cod_settlement_items(company_id, order_id);

        do $$ declare table_name text;
        begin
            foreach table_name in array array['enquiries','cod_settlements','cod_settlement_items'] loop
                execute format('alter table %I enable row level security', table_name);
                execute format('create policy tenali_company_scope on %I to tenali_runtime using (company_id = tenali_current_company()) with check (company_id = tenali_current_company())', table_name);
                execute format('grant select, insert, update on %I to tenali_runtime', table_name);
                execute format('create trigger tenali_company_relationship before insert or update on %I for each row execute function tenali_guard_relationships()', table_name);
                execute format('create trigger tenali_audit_change after insert or update or delete on %I for each row execute function tenali_operational_audit()', table_name);
            end loop;
        end $$;
        """
    )


def downgrade():
    raise NotImplementedError("Online channel history cannot be reversed safely")
