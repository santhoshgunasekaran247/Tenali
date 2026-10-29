"""Separate workspace credentials, platform operators and storefront commerce."""

from alembic import op

revision = "018_customer_accounts"
down_revision = "017_tenant_slug_aliases"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table tenant_users add column company_id uuid references companies(id);
        alter table tenant_users drop constraint tenant_users_email_key;
        do $$ declare account record; member record; scoped_user uuid; first_company uuid;
        begin
            for account in select * from tenant_users loop
                first_company := null;
                for member in select * from tenant_memberships where user_id=account.id order by created_at,company_id loop
                    if first_company is null then
                        first_company := member.company_id;
                        update tenant_users set company_id=member.company_id where id=account.id;
                    else
                        insert into tenant_users(company_id,email,display_name,password_hash,is_active,created_at)
                            values(member.company_id,account.email,account.display_name,account.password_hash,account.is_active,account.created_at)
                            returning id into scoped_user;
                        update tenant_memberships set user_id=scoped_user where company_id=member.company_id and user_id=account.id;
                        update tenant_sessions set user_id=scoped_user where company_id=member.company_id and user_id=account.id;
                        update audit_events set actor_user_id=scoped_user where company_id=member.company_id and actor_user_id=account.id;
                    end if;
                end loop;
            end loop;
        end $$;
        create unique index uq_workspace_email on tenant_users(company_id,email);
        create unique index uq_workspace_user on tenant_users(company_id,id);
        alter table tenant_memberships add constraint fk_membership_workspace_user
            foreign key(company_id,user_id) references tenant_users(company_id,id);
        alter table tenant_sessions add constraint fk_session_workspace_user
            foreign key(company_id,user_id) references tenant_users(company_id,id);

        create table platform_admins (
            id uuid primary key default gen_random_uuid(),email text not null unique,
            display_name text not null,password_hash text not null,is_active boolean not null default true
        );
        create table platform_sessions (
            token_hash text primary key,admin_id uuid not null references platform_admins(id),
            expires_at timestamptz not null
        );
        create table platform_audit (
            id uuid primary key default gen_random_uuid(),admin_id uuid not null references platform_admins(id),
            action text not null,company_id uuid references companies(id),created_at timestamptz not null default now()
        );
        create table shopper_accounts (
            id uuid primary key default gen_random_uuid(),company_id uuid not null references companies(id),
            email text not null,display_name text not null,password_hash text not null,
            is_active boolean not null default true,created_at timestamptz not null default now(),
            unique(company_id,email),unique(company_id,id)
        );
        create table shopper_sessions (
            token_hash text primary key,company_id uuid not null references companies(id),
            shopper_id uuid not null,expires_at timestamptz not null,
            foreign key(company_id,shopper_id) references shopper_accounts(company_id,id)
        );
        create table checkout_settings (
            company_id uuid primary key references companies(id),enabled boolean not null default false,
            credentials text not null,shipping_paise integer not null check(shipping_paise>=0),
            pickup_location text not null,updated_at timestamptz not null default now()
        );
        create table shop_orders (
            id uuid primary key default gen_random_uuid(),company_id uuid not null references companies(id),
            shopper_id uuid not null,request_key uuid not null,request_hash text not null,
            status text not null default 'awaiting_payment' check(status in
                ('awaiting_payment','paid','payment_review','shipping_pending','shipment_booked')),
            items jsonb not null,address jsonb not null,
            subtotal_paise integer not null check(subtotal_paise>0),
            shipping_paise integer not null check(shipping_paise>=0),
            total_paise integer not null check(total_paise=subtotal_paise+shipping_paise),
            provider_key_id text not null,credentials text not null,pickup_location text not null,
            razorpay_order_id text unique,razorpay_payment_id text unique,
            shiprocket_order_id bigint,shipment_id bigint,awb text,courier text,
            shipping_error text,created_at timestamptz not null default now(),paid_at timestamptz,
            unique(company_id,shopper_id,request_key),unique(company_id,id),
            foreign key(company_id,shopper_id) references shopper_accounts(company_id,id)
        );
        create index ix_shop_orders_customer on shop_orders(company_id,shopper_id,created_at);
        create index ix_shop_orders_pending on shop_orders(company_id,status,created_at);
        create function tenali_shop_order_audit() returns trigger language plpgsql
        security definer set search_path=public,pg_temp as $$
        begin
            insert into audit_events(company_id,actor_user_id,action,entity_type,entity_id,old_value,new_value,source_type)
            values(NEW.company_id,nullif(current_setting('app.actor_user_id',true),'')::uuid,
                'SHOP_ORDER_'||TG_OP,'shop_order',NEW.id,
                case when TG_OP='UPDATE' then jsonb_build_object('status',OLD.status) else null end,
                jsonb_build_object('status',NEW.status,'total_paise',NEW.total_paise,
                    'razorpay_order_id',NEW.razorpay_order_id,'razorpay_payment_id',NEW.razorpay_payment_id,
                    'shiprocket_order_id',NEW.shiprocket_order_id,'shipment_id',NEW.shipment_id),
                'storefront_checkout');
            return null;
        end $$;
        revoke all on function tenali_shop_order_audit() from public;
        create trigger shop_order_audit after insert or update on shop_orders
            for each row execute function tenali_shop_order_audit();
        do $$ declare table_name text;
        begin
            foreach table_name in array array['shopper_accounts','shopper_sessions','shop_orders','checkout_settings'] loop
                execute format('alter table %I enable row level security',table_name);
                execute format('create policy company_scope on %I to tenali_runtime using (company_id=tenali_current_company()) with check (company_id=tenali_current_company())',table_name);
            end loop;
        end $$;
        grant select,insert,update on shop_orders to tenali_runtime;
    """)


def downgrade():
    raise NotImplementedError("Account separation and order history cannot be safely reversed")
