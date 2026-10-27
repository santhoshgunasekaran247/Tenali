"""Persist invoice document snapshots."""

from alembic import op

revision = "003_invoice_document"
down_revision = "002_catalog_display_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table invoices add column if not exists document_data jsonb")


def downgrade() -> None:
    raise NotImplementedError("Issued invoice snapshots must be retained")