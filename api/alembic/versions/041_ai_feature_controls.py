"""Platform AI configuration and independent tenant feature entitlements."""
from alembic import op

revision = "041_ai_feature_controls"
down_revision = "040_workflow_guidance"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table ai_platform_settings (
            id boolean primary key default true check (id),
            config jsonb not null default '{}',
            version integer not null default 1 check (version > 0),
            updated_at timestamptz not null default now(),
            updated_by uuid references platform_admins(id)
        );
        insert into ai_platform_settings(id) values(true);
        create table tenant_feature_controls (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            feature_key text not null check (feature_key in ('ai','storefront')),
            platform_allowed boolean not null,
            version integer not null default 1 check (version > 0),
            updated_at timestamptz not null default now(),
            updated_by uuid references platform_admins(id),
            unique(company_id,feature_key)
        );
        create table ai_tenant_limits (
            company_id uuid primary key references companies(id),
            config jsonb not null default '{}',
            version integer not null default 1 check (version > 0),
            updated_at timestamptz not null default now(),
            updated_by uuid references platform_admins(id)
        );
        create table ai_tenant_settings (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null unique references companies(id),
            tenant_enabled boolean not null default false,
            version integer not null default 1 check (version > 0),
            updated_at timestamptz not null default now()
        );
        insert into tenant_feature_controls(company_id,feature_key,platform_allowed)
            select id,'storefront',true from companies union all select id,'ai',false from companies;
        insert into ai_tenant_limits(company_id) select id from companies;
        insert into ai_tenant_settings(company_id) select id from companies;
        create function tenali_seed_feature_controls() returns trigger language plpgsql
            security definer set search_path=public,pg_temp as $$
        begin
            insert into tenant_feature_controls(company_id,feature_key,platform_allowed)
                values(NEW.id,'storefront',true),(NEW.id,'ai',false);
            insert into ai_tenant_limits(company_id) values(NEW.id);
            insert into ai_tenant_settings(company_id) values(NEW.id);
            return NEW;
        end $$;
        revoke all on function tenali_seed_feature_controls() from public;
        create trigger tenali_seed_features after insert on companies
            for each row execute function tenali_seed_feature_controls();

        create function tenali_feature_admin() returns boolean language sql stable
            security definer set search_path=public,pg_temp as $$
            select exists(select 1 from tenant_memberships
                where company_id=tenali_current_company()
                  and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid
                  and is_active and role in ('owner','admin'))
        $$;
        revoke all on function tenali_feature_admin() from public;
        grant execute on function tenali_feature_admin() to tenali_runtime;

        alter table ai_platform_settings enable row level security;
        create policy tenali_ai_defaults_read on ai_platform_settings for select to tenali_runtime using(true);
        grant select on ai_platform_settings to tenali_runtime;
        alter table tenant_feature_controls enable row level security;
        create policy tenali_features_read on tenant_feature_controls for select to tenali_runtime
            using(company_id=tenali_current_company());
        grant select on tenant_feature_controls to tenali_runtime;
        alter table ai_tenant_limits enable row level security;
        create policy tenali_ai_limits_read on ai_tenant_limits for select to tenali_runtime
            using(company_id=tenali_current_company());
        grant select on ai_tenant_limits to tenali_runtime;
        alter table ai_tenant_settings enable row level security;
        create policy tenali_ai_preferences_read on ai_tenant_settings for select to tenali_runtime
            using(company_id=tenali_current_company());
        create policy tenali_ai_preferences_write on ai_tenant_settings for update to tenali_runtime
            using(company_id=tenali_current_company() and tenali_feature_admin())
            with check(company_id=tenali_current_company() and tenali_feature_admin());
        grant select on ai_tenant_settings to tenali_runtime;
        grant update(tenant_enabled,version,updated_at) on ai_tenant_settings to tenali_runtime;
        create trigger tenali_ai_preference_audit after update on ai_tenant_settings
            for each row execute function tenali_operational_audit();
    """)


def downgrade():
    op.execute("""
        drop trigger tenali_seed_features on companies;
        drop function tenali_seed_feature_controls();
        drop table ai_tenant_settings;
        drop function tenali_feature_admin();
        drop table ai_tenant_limits;
        drop table tenant_feature_controls;
        drop table ai_platform_settings;
    """)
