"""Tenant shipping choice, snapshotted on each order."""

from alembic import op

revision = "059_self_shipping"
down_revision = "058_ai_quotation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table checkout_settings add column shipping_provider text not null default 'shiprocket'
            check (shipping_provider in ('shiprocket','self'));
        alter table shop_orders add column shipping_provider text not null default 'shiprocket'
            check (shipping_provider in ('shiprocket','self'));
        grant select (shipping_provider) on checkout_settings to tenali_runtime;
    """)


def downgrade():
    op.execute("""
        alter table shop_orders drop column shipping_provider;
        alter table checkout_settings drop column shipping_provider;
    """)
