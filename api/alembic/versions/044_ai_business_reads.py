"""Opt-in AI financial and business-state read metadata."""
from alembic import op

revision = "044_ai_business_reads"
down_revision = "043_ai_read_capabilities"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        insert into ai_capabilities(key) values
            ('accounts'),('transactions'),('invoices'),('purchases'),('receivables'),
            ('refunds'),('borrowings'),('reorder'),('reconciliation'),('period_locks');
    """)


def downgrade():
    op.execute("""
        delete from ai_tenant_capabilities where capability_key in
            ('accounts','transactions','invoices','purchases','receivables',
             'refunds','borrowings','reorder','reconciliation','period_locks');
        delete from ai_capabilities where key in
            ('accounts','transactions','invoices','purchases','receivables',
             'refunds','borrowings','reorder','reconciliation','period_locks');
    """)
