"""Link borrowing entries to their originating account transactions."""

from alembic import op

revision = "020_borrowing_source_links"
down_revision = "019_product_minimum_order"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "alter table borrowings add column source_transaction_id uuid references account_transactions(id)"
    )
    op.execute(
        """
        create unique index uq_borrowings_source_transaction
        on borrowings(company_id, source_transaction_id)
        where source_transaction_id is not null
        """
    )


def downgrade():
    op.execute("drop index uq_borrowings_source_transaction")
    op.execute("alter table borrowings drop column source_transaction_id")
