"""Persist the reversal reference required by transaction history queries."""

from alembic import op

revision = "007_transaction_reversal_ref"
down_revision = "006_receipt_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        alter table account_transactions add column if not exists
            reversal_of_transaction_id uuid references account_transactions(id);
        create unique index if not exists uq_account_transactions_reversal_once
            on account_transactions(company_id, reversal_of_transaction_id)
            where reversal_of_transaction_id is not null;
    """)


def downgrade() -> None:
    raise NotImplementedError("Transaction reversal references must be retained for audit")