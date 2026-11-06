"""Let each workspace switch its public storefront on or off."""
from alembic import op

revision = "036_storefront_enabled"
down_revision = "035_invoice_store_codes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table companies add column storefront_enabled boolean not null default true")


def downgrade():
    op.execute("alter table companies drop column storefront_enabled")
