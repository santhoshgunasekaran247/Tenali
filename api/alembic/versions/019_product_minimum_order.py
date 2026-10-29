"""Set a minimum online order quantity per product."""

from alembic import op

revision = "019_product_minimum_order"
down_revision = "018_customer_accounts"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""alter table products add column minimum_order_quantity integer not null default 1
        constraint products_minimum_order_quantity_check check (minimum_order_quantity between 1 and 100)""")
    op.execute("""update companies set storefront_content=jsonb_set(storefront_content,'{product,online_purchase_help}',
        to_jsonb('Add products to your cart, change quantities and pay for them together. Sign in at checkout; delivery charges are shown before payment.'::text))
        where storefront_content #>> '{product,online_purchase_help}' =
        'Buy Online is for the listed price: sign in, choose quantity and pay securely. Delivery charges are shown before payment.'""")
    op.execute("""update companies set storefront_content=jsonb_set(storefront_content,'{product,checkout_variant_required}',
        to_jsonb('Select a size / colour to add to your cart.'::text))
        where storefront_content #>> '{product,checkout_variant_required}' = 'Select a size / colour to buy online.'""")


def downgrade():
    op.execute("alter table products drop column minimum_order_quantity")
