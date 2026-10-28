"""Preserve cancellation dates and reasons without deleting source documents."""

from alembic import op

revision="011_document_cancellation"
down_revision="010_posting_controls"
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""
        alter table invoices add column if not exists cancelled_at date, add column if not exists cancellation_reason text;
        alter table purchases add column if not exists cancelled_at date, add column if not exists cancellation_reason text;
    """)


def downgrade():
    raise NotImplementedError("Cancellation history must be retained")