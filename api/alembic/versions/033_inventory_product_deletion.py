"""Allow tenant-scoped deletion of unused inventory products."""
from alembic import op

revision = "033_inventory_product_deletion"
down_revision = "032_document_storage_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("grant delete on products, stock_balances, vendor_contributions to tenali_runtime")


def downgrade():
    op.execute("revoke delete on products, stock_balances, vendor_contributions from tenali_runtime")
