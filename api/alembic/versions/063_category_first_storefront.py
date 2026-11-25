"""Add the category-first storefront template."""
from alembic import op

revision = "063_category_first_storefront"
down_revision = "062_storefront_builder"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table companies drop constraint if exists companies_storefront_template_check")
    op.execute("""
        alter table companies
        add constraint companies_storefront_template_check
        check (storefront_template in (
            'current', 'marketplace', 'category_first', 'boutique', 'heritage', 'supermarket', 'jewellery'
        ))
    """)


def downgrade():
    op.execute("""
        update companies set storefront_template = 'marketplace'
        where storefront_template = 'category_first'
    """)
    op.execute("alter table companies drop constraint if exists companies_storefront_template_check")
    op.execute("""
        alter table companies
        add constraint companies_storefront_template_check
        check (storefront_template in (
            'current', 'marketplace', 'boutique', 'heritage', 'supermarket', 'jewellery'
        ))
    """)
