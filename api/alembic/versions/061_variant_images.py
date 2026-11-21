"""Add an optional storefront image and retained original for each variant."""
from alembic import op

revision = "061_variant_images"
down_revision = "060_render_domains"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table product_variants add column if not exists image_url text")
    op.execute("alter table product_variants add column if not exists image_original_url text")


def downgrade():
    op.execute("alter table product_variants drop column if exists image_original_url")
    op.execute("alter table product_variants drop column if exists image_url")
