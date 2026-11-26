"""Store uploaded brand images."""
from alembic import op

revision = "066_brand_image"
down_revision = "065_product_image_background"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table brands add column if not exists image_url text")


def downgrade():
    op.execute("alter table brands drop column if exists image_url")
