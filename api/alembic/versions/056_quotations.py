"""Persist non-posting billing quotations separately from invoices."""
from alembic import op

revision = "056_quotations"
down_revision = "055_ai_store_create"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table quotations (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            store_id uuid not null references stores(id),
            customer_party_id uuid not null references parties(id),
            quotation_number text not null,
            quotation_date date not null,
            reference text,
            notes text,
            document_data jsonb not null,
            created_at timestamptz not null default now(),
            unique(company_id, quotation_number)
        );
        create index ix_quotations_company_store on quotations(company_id, store_id, created_at desc);
        alter table quotations enable row level security;
        create policy tenali_company_scope on quotations to tenali_runtime
            using (company_id = tenali_current_company()) with check (company_id = tenali_current_company());
        grant select, insert on quotations to tenali_runtime;
        create trigger tenali_company_relationship before insert or update on quotations
            for each row execute function tenali_guard_relationships();
    """)


def downgrade():
    raise NotImplementedError("Saved quotations cannot be discarded by downgrade")
