"""Allow products to belong to multiple categories."""
from alembic import op

revision = "064_product_categories"
down_revision = ("063_category_first_storefront", "063_storefront_runtime_access")
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table if not exists product_category_products (
            company_id uuid not null,
            product_id uuid not null,
            category_id uuid not null,
            primary key (company_id, product_id, category_id),
            foreign key (company_id, product_id) references products(company_id, id) on delete cascade,
            foreign key (company_id, category_id) references product_categories(company_id, id) on delete cascade
        );
        create index if not exists idx_product_category_products_category
            on product_category_products(company_id, category_id, product_id);
        insert into product_category_products(company_id, product_id, category_id)
        select company_id, id, category_id from products where category_id is not null
        on conflict do nothing;
        alter table product_category_products enable row level security;
        drop policy if exists tenali_company_scope on product_category_products;
        create policy tenali_company_scope on product_category_products to tenali_runtime
            using (company_id = tenali_current_company())
            with check (company_id = tenali_current_company());
        grant select, insert, update, delete on product_category_products to tenali_runtime;
    """)


def downgrade():
    op.execute("""
        do $$ begin
            if exists (
                select 1 from product_category_products
                group by company_id, product_id having count(*) > 1
            ) then
                raise exception 'Cannot downgrade while products have multiple categories';
            end if;
        end $$;
        drop table product_category_products;
    """)
