"""Keep old storefront addresses resolving after tenant URL changes."""

from alembic import op

revision = "017_tenant_slug_aliases"
down_revision = "016_storefront_content"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table if not exists tenant_slug_aliases (
            company_id uuid not null references companies(id) on delete cascade,
            tenant_slug text not null unique,
            created_at timestamptz not null default now(),
            primary key(company_id, tenant_slug)
        );
        insert into tenant_slug_aliases(company_id,tenant_slug)
            select id,tenant_slug from companies where tenant_slug is not null
            on conflict(tenant_slug) do nothing;
        alter table tenant_slug_aliases enable row level security;
        drop policy if exists tenant_slug_aliases_scope on tenant_slug_aliases;
        create policy tenant_slug_aliases_scope on tenant_slug_aliases
            using (company_id=tenali_current_company())
            with check (company_id=tenali_current_company());
        grant select,insert on tenant_slug_aliases to tenali_runtime;
    """)


def downgrade():
    raise NotImplementedError("Tenant URL aliases must be retained")
