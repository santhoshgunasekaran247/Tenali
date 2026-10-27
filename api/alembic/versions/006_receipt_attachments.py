"""Persist receipt and bill attachment bytes with existing document links."""

from alembic import op

revision = "006_receipt_attachments"
down_revision = "005_hsn_master"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        alter table documents add column if not exists file_content bytea;
        create index if not exists idx_document_links_entity on document_links(entity_type, entity_id);
    """)


def downgrade() -> None:
    raise NotImplementedError("Receipt attachments must be retained for audit")