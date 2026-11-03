"""Store independently reviewed drafts and published platform/store policies."""
from alembic import op

revision = "034_public_policies"
down_revision = "033_inventory_product_deletion"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table legal_policies (
            id uuid primary key default gen_random_uuid(),
            company_id uuid references companies(id),
            kind text not null check (kind in
                ('privacy','terms','shipping','payment','returns','data-deletion','contact')),
            draft jsonb not null,
            revision integer not null default 1 check (revision > 0),
            published jsonb,
            published_revision integer,
            published_at timestamptz,
            updated_at timestamptz not null default now(),
            check (company_id is not null or kind in ('privacy','terms','data-deletion','contact')),
            check ((published is null and published_revision is null and published_at is null)
                or (published is not null and published_revision is not null and published_at is not null))
        );
        create unique index uq_tenant_legal_policy on legal_policies(company_id,kind)
            where company_id is not null;
        create unique index uq_platform_legal_policy on legal_policies(kind)
            where company_id is null;
        alter table legal_policies enable row level security;
        create policy company_scope on legal_policies to tenali_runtime
            using (company_id=tenali_current_company())
            with check (company_id=tenali_current_company());
    """)


def downgrade():
    raise NotImplementedError("Published legal documents must be preserved")
