"""Store the selected product photo background."""
from alembic import op

revision = "065_product_image_background"
down_revision = "064_product_categories"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""alter table products add column if not exists image_background text
        not null default '#ffffff' check (image_background ~ '^#[0-9a-fA-F]{6}$')""")


def downgrade():
    op.execute("alter table products drop column if exists image_background")
