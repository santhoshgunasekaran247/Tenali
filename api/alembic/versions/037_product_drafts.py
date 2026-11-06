"""Mark products created from purchase bills as drafts until the team confirms them."""
from alembic import op

revision = "037_product_drafts"
down_revision = "036_storefront_enabled"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table products add column is_draft boolean not null default false")


def downgrade():
    op.execute("alter table products drop column is_draft")
