"""Stock is held per store; transfers move stock between stores of one company."""

from alembic import op

revision = "023_stock_per_store"
down_revision = "022_stores"
branch_labels = None
depends_on = None

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def upgrade():
    op.execute(
        """
        do $$
        begin
            if exists (select 1 from companies c where not exists
                       (select 1 from stores s where s.company_id = c.id and s.is_default and s.holds_stock)) then
                raise exception 'Every company needs a default stock-holding store before migrating stock';
            end if;
        end $$;

        alter table stock_balances add column if not exists store_id uuid references stores(id);
        alter table stock_movements add column if not exists store_id uuid references stores(id);

        update stock_balances b set store_id = s.id
        from stores s where s.company_id = b.company_id and s.is_default and b.store_id is null;
        update stock_movements m set store_id = s.id
        from stores s where s.company_id = m.company_id and s.is_default and m.store_id is null;

        create temporary table stock_totals_before on commit drop as
        select company_id, product_id, variant_id, sum(quantity) as quantity
        from stock_balances group by company_id, product_id, variant_id;

        with ranked as (
            select id, quantity,
                   first_value(id) over (partition by company_id, store_id, product_id, coalesce(variant_id, cast(:zero as uuid))
                                         order by id) as keeper
            from stock_balances
        ),
        merged as (
            select keeper, sum(quantity) as quantity, count(*) as rows
            from ranked group by keeper having count(*) > 1
        ),
        updated as (
            update stock_balances b set quantity = merged.quantity
            from merged where b.id = merged.keeper returning b.id
        )
        delete from stock_balances b using ranked
        where b.id = ranked.id and ranked.id <> ranked.keeper;

        do $$
        begin
            if exists (
                select 1 from stock_totals_before before
                full outer join (select company_id, product_id, variant_id, sum(quantity) as quantity
                                 from stock_balances group by company_id, product_id, variant_id) after
                  on after.company_id = before.company_id and after.product_id = before.product_id
                 and after.variant_id is not distinct from before.variant_id
                where before.quantity is distinct from after.quantity
            ) then
                raise exception 'Stock balance merge changed a total; migration aborted';
            end if;
        end $$;

        alter table stock_balances alter column store_id set not null;
        alter table stock_movements alter column store_id set not null;

        do $$ declare constraint_name text;
        begin
            for constraint_name in
                select conname from pg_constraint
                where conrelid = 'stock_balances'::regclass and contype = 'u'
            loop
                execute format('alter table stock_balances drop constraint %I', constraint_name);
            end loop;
            for constraint_name in
                select conname from pg_constraint
                where conrelid = 'stock_movements'::regclass and contype = 'c'
                  and pg_get_constraintdef(oid) like '%movement_type%'
            loop
                execute format('alter table stock_movements drop constraint %I', constraint_name);
            end loop;
        end $$;

        create unique index uq_stock_balances_store_item
            on stock_balances(company_id, store_id, product_id, coalesce(variant_id, cast(:zero as uuid)));
        create index ix_stock_movements_store_item
            on stock_movements(company_id, store_id, product_id, variant_id, created_at);
        alter table stock_movements add constraint stock_movements_movement_type_check
            check (movement_type in ('PURCHASE','SALE','GIFT_IN','GIFT_OUT','ADJUSTMENT_IN','ADJUSTMENT_OUT',
                                     'TRANSFER_IN','TRANSFER_OUT'));

        create table stock_transfers (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            from_store_id uuid not null references stores(id),
            to_store_id uuid not null references stores(id),
            transfer_date date not null default current_date,
            reference text,
            notes text not null check (length(trim(notes)) > 0),
            lines jsonb not null,
            reversal_of_transfer_id uuid references stock_transfers(id),
            created_by uuid references user_profiles(id),
            created_at timestamptz not null default now(),
            check (from_store_id <> to_store_id)
        );
        create unique index uq_stock_transfers_reversal
            on stock_transfers(company_id, reversal_of_transfer_id) where reversal_of_transfer_id is not null;
        create index ix_stock_transfers_company_date on stock_transfers(company_id, transfer_date desc, created_at desc);
        alter table stock_transfers enable row level security;
        create policy tenali_company_scope on stock_transfers to tenali_runtime
            using (company_id = tenali_current_company()) with check (company_id = tenali_current_company());
        grant select, insert on stock_transfers to tenali_runtime;
        create trigger tenali_company_relationship before insert or update on stock_transfers
            for each row execute function tenali_guard_relationships();
        create trigger tenali_audit_change after insert or update or delete on stock_transfers
            for each row execute function tenali_operational_audit();
        """.replace(":zero", f"'{ZERO_UUID}'")
    )


def downgrade():
    raise NotImplementedError("Per-store stock cannot be collapsed back safely")
