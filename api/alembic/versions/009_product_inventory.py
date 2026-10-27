"""Extend shared products with inventory attributes and vendor offers."""

from alembic import op

revision = "009_product_inventory"
down_revision = "008_company_site_theme"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        alter table products
            add column if not exists item_name text,
            add column if not exists size text,
            add column if not exists colour text,
            add column if not exists weight numeric(14,3),
            add column if not exists height numeric(14,3),
            add column if not exists width numeric(14,3),
            add column if not exists length numeric(14,3),
            add column if not exists attributes jsonb not null default '{}'::jsonb,
            add column if not exists pricing_mode text not null default 'price',
            add column if not exists discount_percent numeric(5,2) not null default 0,
            add column if not exists catalog_visible boolean not null default true,
            add column if not exists reorder_target numeric(14,3) not null default 0,
            add column if not exists reorder_enabled boolean not null default false,
            add column if not exists reorder_reminder_date date;
        alter table product_variants
            add column if not exists attributes jsonb not null default '{}'::jsonb,
            add column if not exists pricing_mode text not null default 'inherit',
            add column if not exists discount_percent numeric(5,2) not null default 0,
            add column if not exists preferred_vendor_id uuid references parties(id),
            add column if not exists reorder_level numeric(14,3) not null default 0,
            add column if not exists reorder_target numeric(14,3) not null default 0,
            add column if not exists reorder_enabled boolean not null default false,
            add column if not exists reorder_reminder_date date;
        alter table vendor_contributions
            add column if not exists available_quantity numeric(14,3) not null default 0,
            add column if not exists availability text not null default 'UNKNOWN',
            add column if not exists lead_time_days integer not null default 0;
        create index if not exists idx_variants_product_active on product_variants(product_id, is_active);
        create index if not exists idx_vendor_offers_product on vendor_contributions(product_id, variant_id, vendor_id);
        create index if not exists idx_stock_balances_item on stock_balances(company_id, product_id, variant_id);
    """)


def downgrade() -> None:
    raise NotImplementedError("Shared product and stock history must be retained")