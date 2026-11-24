"""Add storefront templates, sections, and product tags."""
from alembic import op

revision = "062_storefront_builder"
down_revision = "061_variant_images"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table companies
        add column if not exists storefront_template text not null default 'current'
    """)
    op.execute("""
        do $$ begin
            if not exists (
                select 1 from pg_constraint
                where conname = 'companies_storefront_template_check'
            ) then
                alter table companies
                add constraint companies_storefront_template_check
                check (storefront_template in (
                    'current', 'marketplace', 'boutique', 'heritage', 'supermarket', 'jewellery'
                ));
            end if;
        end $$
    """)
    op.execute("create unique index if not exists uq_products_company_id on products(company_id, id)")
    op.execute("create unique index if not exists uq_product_categories_company_id on product_categories(company_id, id)")
    op.execute("create unique index if not exists uq_brands_company_id on brands(company_id, id)")
    op.execute("""
        create table if not exists product_tags (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id) on delete cascade,
            code text not null,
            name text not null,
            created_at timestamptz not null default now(),
            unique(company_id, code),
            unique(company_id, id)
        )
    """)
    op.execute("""
        create table if not exists product_tag_products (
            company_id uuid not null,
            tag_id uuid not null,
            product_id uuid not null,
            primary key(company_id, tag_id, product_id),
            foreign key(company_id, tag_id) references product_tags(company_id, id) on delete cascade,
            foreign key(company_id, product_id) references products(company_id, id) on delete cascade
        )
    """)
    op.execute("""
        create table if not exists storefront_sections (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id) on delete cascade,
            section_key text not null,
            section_type text not null check (section_type in ('hero', 'products', 'categories', 'brands')),
            title text not null,
            eyebrow text not null default '',
            description text not null default '',
            image_url text,
            sort_order integer not null default 0,
            is_enabled boolean not null default true,
            configuration jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique(company_id, section_key),
            unique(company_id, id)
        )
    """)
    op.execute("""
        create table if not exists storefront_section_products (
            company_id uuid not null,
            section_id uuid not null,
            product_id uuid not null,
            sort_order integer not null default 0,
            primary key(section_id, product_id),
            foreign key(company_id, section_id) references storefront_sections(company_id, id) on delete cascade,
            foreign key(company_id, product_id) references products(company_id, id) on delete cascade
        )
    """)
    op.execute("""
        create table if not exists storefront_section_categories (
            company_id uuid not null,
            section_id uuid not null,
            category_id uuid not null,
            sort_order integer not null default 0,
            primary key(section_id, category_id),
            foreign key(company_id, section_id) references storefront_sections(company_id, id) on delete cascade,
            foreign key(company_id, category_id) references product_categories(company_id, id) on delete cascade
        )
    """)
    op.execute("""
        create table if not exists storefront_section_brands (
            company_id uuid not null,
            section_id uuid not null,
            brand_id uuid not null,
            sort_order integer not null default 0,
            primary key(section_id, brand_id),
            foreign key(company_id, section_id) references storefront_sections(company_id, id) on delete cascade,
            foreign key(company_id, brand_id) references brands(company_id, id) on delete cascade
        )
    """)
    op.execute("create index if not exists idx_storefront_sections_order on storefront_sections(company_id, is_enabled, sort_order)")


def downgrade():
    op.execute("drop table if exists storefront_section_brands")
    op.execute("drop table if exists storefront_section_categories")
    op.execute("drop table if exists storefront_section_products")
    op.execute("drop table if exists storefront_sections")
    op.execute("drop table if exists product_tag_products")
    op.execute("drop table if exists product_tags")
    op.execute("drop index if exists uq_brands_company_id")
    op.execute("drop index if exists uq_product_categories_company_id")
    op.execute("drop index if exists uq_products_company_id")
    op.execute("alter table companies drop constraint if exists companies_storefront_template_check")
    op.execute("alter table companies drop column if exists storefront_template")
