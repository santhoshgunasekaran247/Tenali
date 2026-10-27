"""Persist configurable site colours independently of invoice branding."""

from alembic import op

revision = "008_company_site_theme"
down_revision = "007_transaction_reversal_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table companies add column if not exists site_theme jsonb not null default '{}'::jsonb")


def downgrade() -> None:
    raise NotImplementedError("Company branding settings must be retained")