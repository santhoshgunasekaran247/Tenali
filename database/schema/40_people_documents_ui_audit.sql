create table if not exists employees (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    party_id uuid references parties(id),
    employee_code text,
    name text not null,
    nickname text,
    phone text,
    email text,
    role text,
    monthly_salary numeric(14,2),
    portal_user boolean not null default false,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(company_id, employee_code)
);

create table if not exists salary_transactions (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    employee_id uuid not null references employees(id),
    amount numeric(14,2) not null check (amount > 0),
    paid_from_account_id uuid references accounts(id),
    payment_mode text,
    reference text,
    salary_date date not null default current_date,
    document_id uuid,
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now()
);

create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    document_type text not null,
    file_name text not null,
    storage_path text not null,
    mime_type text,
    file_size bigint,
    file_content bytea,
    uploaded_by uuid references user_profiles(id),
    created_at timestamptz not null default now()
);

create table if not exists document_links (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    entity_type text not null,
    entity_id uuid not null,
    created_at timestamptz not null default now()
);

create table if not exists navigation_items (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id),
    label text not null,
    route text not null,
    icon text,
    parent_id uuid references navigation_items(id),
    sort_order integer not null default 0,
    is_enabled boolean not null default true,
    created_at timestamptz not null default now()
);

create table if not exists page_configurations (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id),
    page_key text not null,
    title text,
    configuration jsonb not null default '{}'::jsonb,
    is_enabled boolean not null default true,
    unique(company_id, page_key)
);

create table if not exists dashboard_widgets (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id),
    widget_key text not null,
    title text,
    configuration jsonb not null default '{}'::jsonb,
    sort_order integer not null default 0,
    is_enabled boolean not null default true,
    unique(company_id, widget_key)
);

create table if not exists theme_settings (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id),
    theme_key text not null,
    configuration jsonb not null default '{}'::jsonb,
    unique(company_id, theme_key)
);

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
);

create table if not exists storefront_section_products (
    company_id uuid not null,
    section_id uuid not null,
    product_id uuid not null,
    sort_order integer not null default 0,
    primary key(section_id, product_id),
    foreign key(company_id, section_id) references storefront_sections(company_id, id) on delete cascade,
    foreign key(company_id, product_id) references products(company_id, id) on delete cascade
);

create table if not exists storefront_section_categories (
    company_id uuid not null,
    section_id uuid not null,
    category_id uuid not null,
    sort_order integer not null default 0,
    primary key(section_id, category_id),
    foreign key(company_id, section_id) references storefront_sections(company_id, id) on delete cascade,
    foreign key(company_id, category_id) references product_categories(company_id, id) on delete cascade
);

create table if not exists storefront_section_brands (
    company_id uuid not null,
    section_id uuid not null,
    brand_id uuid not null,
    sort_order integer not null default 0,
    primary key(section_id, brand_id),
    foreign key(company_id, section_id) references storefront_sections(company_id, id) on delete cascade,
    foreign key(company_id, brand_id) references brands(company_id, id) on delete cascade
);

create index if not exists idx_storefront_sections_order
    on storefront_sections(company_id, is_enabled, sort_order);

create table if not exists audit_events (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id),
    user_id uuid references user_profiles(id),
    action text not null,
    entity_type text,
    entity_id uuid,
    old_value jsonb,
    new_value jsonb,
    source_type text,
    source_id uuid,
    created_at timestamptz not null default now()
);
