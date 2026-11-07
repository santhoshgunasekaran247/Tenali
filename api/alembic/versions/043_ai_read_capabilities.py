"""Reviewed, opt-in AI read capabilities and current member scope."""
from alembic import op

revision = "043_ai_read_capabilities"
down_revision = "042_ai_conversations"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table ai_capabilities (
            key text primary key,
            enabled boolean not null default false,
            schema_fingerprint text not null default '',
            version integer not null default 1 check(version>0),
            updated_at timestamptz not null default now(),
            updated_by uuid references platform_admins(id)
        );
        insert into ai_capabilities(key) values
            ('stores'),('products'),('parties'),('hsn'),('brands'),('categories');
        create table ai_tenant_capabilities (
            company_id uuid not null references companies(id),
            capability_key text not null references ai_capabilities(key),
            allowed boolean not null default false,
            version integer not null default 1 check(version>0),
            updated_at timestamptz not null default now(),
            updated_by uuid references platform_admins(id),
            primary key(company_id,capability_key)
        );
        alter table ai_capabilities enable row level security;
        create policy ai_capabilities_read on ai_capabilities for select to tenali_runtime using(true);
        grant select on ai_capabilities to tenali_runtime;
        alter table ai_tenant_capabilities enable row level security;
        create policy ai_tenant_capabilities_read on ai_tenant_capabilities for select to tenali_runtime
            using(company_id=tenali_current_company());
        grant select on ai_tenant_capabilities to tenali_runtime;
        create function tenali_ai_member_scope() returns table(role text,store_ids uuid[],modules text[])
            language sql stable security definer set search_path=public,pg_temp as $$
            select m.role::text,m.store_ids,m.modules from tenant_memberships m
                join tenant_users u on u.id=m.user_id and u.company_id=m.company_id and u.is_active
                where m.company_id=tenali_current_company() and m.is_active and m.role<>'viewer'
                and m.user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid
        $$;
        revoke all on function tenali_ai_member_scope() from public;
        grant execute on function tenali_ai_member_scope() to tenali_runtime;
    """)


def downgrade():
    op.execute("""
        drop function tenali_ai_member_scope();
        drop table ai_tenant_capabilities;
        drop table ai_capabilities;
    """)
