"""Add catalog display fields for prototype parity.

Revision ID: 002_catalog_display_fields
Revises: 001_initial_schema
"""

from alembic import op

revision = "002_catalog_display_fields"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table if exists brands
            add column if not exists code text,
            add column if not exists description text;

        alter table if exists product_categories
            add column if not exists code text,
            add column if not exists display_title text,
            add column if not exists description text,
            add column if not exists image_url text,
            add column if not exists home_order integer not null default 999;

        alter table if exists products
            add column if not exists image_url text,
            add column if not exists image_urls text,
            add column if not exists mrp_display text,
            add column if not exists selling_price_display text,
            add column if not exists home_order integer not null default 999;

        create unique index if not exists uq_brands_company_code on brands(company_id, code)
            where code is not null;

        create unique index if not exists uq_categories_company_code on product_categories(company_id, code)
            where code is not null;
        """
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade is intentionally not provided for this migration."
    )
