"""Configure company invoice presentation and signature."""

from alembic import op

revision = "004_company_invoice_settings"
down_revision = "003_invoice_document"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table companies add column if not exists invoice_settings jsonb not null default '{}'::jsonb")


def downgrade() -> None:
    raise NotImplementedError("Company invoice settings must be retained")