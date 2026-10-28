"""Persist editable tenant storefront copy."""

from alembic import op

revision = "016_storefront_content"
down_revision = "015_domain_claims"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table companies add column if not exists storefront_content jsonb not null default '{}'::jsonb")


def downgrade():
    raise NotImplementedError("Tenant storefront copy must be retained")
