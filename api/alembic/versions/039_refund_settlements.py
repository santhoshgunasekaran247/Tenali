"""Refunds created when a paid invoice or purchase is cancelled.

Cancelling a paid document reverses each payment transaction (nothing is deleted) and records one PENDING
refund settlement per reversal. Staff later confirm the money actually moved, correcting the account, mode,
date and reference of the reversal, which marks it SETTLED.
"""
from alembic import op

revision = "039_refund_settlements"
down_revision = "038_transaction_deletions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table refund_settlements (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            direction text not null check (direction in ('PAY_CUSTOMER', 'RECEIVE_VENDOR')),
            document_type text not null check (document_type in ('invoice', 'purchase')),
            document_id uuid not null,
            document_number text,
            party_id uuid references parties(id),
            original_transaction_id uuid not null references account_transactions(id),
            reversal_transaction_id uuid not null unique references account_transactions(id),
            amount numeric(14, 2) not null check (amount > 0),
            status text not null default 'PENDING' check (status in ('PENDING', 'SETTLED')),
            reason text,
            settled_on date,
            account_id uuid references accounts(id),
            payment_mode text,
            reference text,
            notes text,
            settled_by uuid,
            settled_at timestamptz,
            created_at timestamptz not null default now(),
            check (status = 'PENDING' or (settled_on is not null and account_id is not null))
        );
        create index idx_refund_settlements_status on refund_settlements(company_id, status, created_at desc);
        create index idx_refund_settlements_document on refund_settlements(company_id, document_type, document_id);
        alter table refund_settlements enable row level security;
        create policy tenali_company_scope on refund_settlements to tenali_runtime
            using (company_id = tenali_current_company()) with check (company_id = tenali_current_company());
        grant select, insert, update, delete on refund_settlements to tenali_runtime;
        create trigger tenali_transaction_delete before delete on refund_settlements
            for each row execute function tenali_transaction_delete('guard');
    """)


def downgrade():
    op.execute("drop table refund_settlements")
