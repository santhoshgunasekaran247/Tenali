"""Add company HSN/GST masters and purchase line snapshots."""

from alembic import op

revision = "005_hsn_master"
down_revision = "004_company_invoice_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        create table if not exists hsn_masters (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            code text not null check (code ~ '^([0-9]{4}|[0-9]{6}|[0-9]{8})$'),
            description text not null check (length(trim(description)) > 0),
            gst_rate numeric(5,2) not null check (gst_rate between 0 and 100),
            is_active boolean not null default true,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique(company_id, code)
        );
        alter table purchases add column if not exists line_items jsonb not null default '[]'::jsonb;
    """)


def downgrade() -> None:
    raise NotImplementedError("Used tax masters and document snapshots must be retained")