create table if not exists brands (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    code text,
    name text not null,
    is_active boolean not null default true,
    description text,
    unique(company_id, name)
);

create table if not exists product_categories (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    code text,
    name text not null,
    display_title text,
    description text,
    image_url text,
    home_order integer not null default 999,
    parent_id uuid references product_categories(id),
    is_active boolean not null default true,
    unique(company_id, name)
);

create table if not exists hsn_masters (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    code text not null check (code ~ '^([0-9]{4}|[0-9]{6}|[0-9]{8})$'),
    description text not null check (length(trim(description)) > 0),
    gst_rate numeric(5,2) not null check (gst_rate between 0 and 100),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(company_id, code)
);

create table if not exists products (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    portal_product_id text not null,
    sku text,
    name text not null,
    brand_id uuid references brands(id),
    category_id uuid references product_categories(id),
    description text,
    image_url text,
    image_urls text,
    mrp numeric(14,2),
    mrp_display text,
    selling_price numeric(14,2),
    selling_price_display text,
    hsn_code text,
    gst_rate numeric(6,2),
    uom text,
    best_seller boolean not null default false,
    sru_special boolean not null default false,
    home_order integer not null default 999,
    reorder_level numeric(14,3) not null default 0,
    preferred_vendor_id uuid references parties(id),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(company_id, portal_product_id)
);

create table if not exists product_variants (
    id uuid primary key default gen_random_uuid(),
    product_id uuid not null references products(id) on delete cascade,
    variant_name text,
    sku text,
    size text,
    colour text,
    gtin text,
    unit_count numeric(14,3),
    weight numeric(14,3),
    height numeric(14,3),
    width numeric(14,3),
    length numeric(14,3),
    item_name text,
    description text,
    mrp numeric(14,2),
    selling_price numeric(14,2),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists product_images (
    id uuid primary key default gen_random_uuid(),
    product_id uuid not null references products(id) on delete cascade,
    variant_id uuid references product_variants(id) on delete cascade,
    storage_path text not null,
    alt_text text,
    sort_order integer not null default 0,
    is_primary boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists vendor_contributions (
    id uuid primary key default gen_random_uuid(),
    vendor_id uuid not null references parties(id),
    product_id uuid not null references products(id),
    variant_id uuid references product_variants(id),
    sku text,
    size text,
    colour text,
    gtin text,
    unit_count numeric(14,3),
    weight numeric(14,3),
    height numeric(14,3),
    width numeric(14,3),
    length numeric(14,3),
    item_name text,
    description text,
    mrp numeric(14,2),
    buying_price numeric(14,2),
    selling_price numeric(14,2),
    vendor_product_url text,
    vendor_reference text,
    is_active boolean not null default true,
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists stock_balances (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    product_id uuid not null references products(id),
    variant_id uuid references product_variants(id),
    quantity numeric(14,3) not null default 0,
    unique(company_id, product_id, variant_id)
);

create table if not exists stock_movements (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    product_id uuid not null references products(id),
    variant_id uuid references product_variants(id),
    movement_type text not null check (movement_type in ('PURCHASE','SALE','GIFT_IN','GIFT_OUT','ADJUSTMENT_IN','ADJUSTMENT_OUT')),
    quantity numeric(14,3) not null check (quantity > 0),
    unit_value numeric(14,2),
    reference_type text,
    reference_id uuid,
    notes text,
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now()
);
