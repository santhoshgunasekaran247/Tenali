"""Keep the uploaded original beside each enhanced website display image of a product."""
from alembic import op

revision = "054_product_image_originals"
down_revision = "053_ai_hsn_create"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table products add column if not exists image_originals jsonb not null default '{}'::jsonb")


def downgrade():
    op.execute("alter table products drop column if exists image_originals")
