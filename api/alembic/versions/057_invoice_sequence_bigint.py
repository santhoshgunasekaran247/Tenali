"""Allow the compact GST invoice series to use the full 16-character limit."""
from alembic import op

revision = "057_invoice_sequence_bigint"
down_revision = "056_quotations"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table document_sequences alter column last_number type bigint")


def downgrade():
    raise NotImplementedError("Invoice sequence capacity must not be reduced")
