"""Prevent multiple receivables for the same invoice."""

from alembic import op

revision = "021_unique_invoice_receivable"
down_revision = "020_borrowing_source_links"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        do $$
        begin
            if exists (
                select 1 from receivables where invoice_id is not null
                group by company_id, invoice_id having count(*) > 1
            ) then
                raise exception 'Duplicate invoice receivables must be resolved before this migration';
            end if;
        end $$
        """
    )
    op.execute(
        """
        create unique index uq_receivables_company_invoice
        on receivables(company_id, invoice_id) where invoice_id is not null
        """
    )


def downgrade():
    op.execute("drop index uq_receivables_company_invoice")
