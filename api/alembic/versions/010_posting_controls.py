"""Persist retry-safe posting responses and stock source links."""

from alembic import op

revision = "010_posting_controls"
down_revision = "009_product_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        create table if not exists posting_requests (
            company_id uuid not null references companies(id),
            operation text not null,
            request_key text not null,
            payload_hash text not null,
            response jsonb not null,
            created_at timestamptz not null default now(),
            primary key(company_id,operation,request_key)
        );
        create index if not exists idx_stock_movement_source on stock_movements(company_id,reference_type,reference_id);
    """)


def downgrade() -> None:
    raise NotImplementedError("Posting history must be retained")