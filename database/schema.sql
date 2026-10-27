-- Tenali initial PostgreSQL schema
create extension if not exists pgcrypto;

create table if not exists companies (
    id uuid primary key default gen_random_uuid(),
    company_name text not null,
    nickname text,
    logo_url text,
    gst_number text,
    udyam_number text,
    phone text,
    email text,
    address text,
    website text,
    social_links jsonb not null default '{}'::jsonb,
    invoice_settings jsonb not null default '{}'::jsonb,
    site_theme jsonb not null default '{}'::jsonb,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists roles (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    description text,
    is_active boolean not null default true,
    created_at timestamptz not null default now()
);

create table if not exists permissions (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    description text,
    created_at timestamptz not null default now()
);

create table if not exists role_permissions (
    role_id uuid not null references roles(id) on delete cascade,
    permission_id uuid not null references permissions(id) on delete cascade,
    primary key (role_id, permission_id)
);

create table if not exists user_profiles (
    id uuid primary key,
    company_id uuid references companies(id),
    role_id uuid references roles(id),
    display_name text,
    phone text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists parties (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    party_type text not null check (party_type in ('customer','vendor','customer_vendor','friend','employee','other')),
    nickname text,
    legal_name text not null,
    contact_person text,
    phone text,
    email text,
    address text,
    gst_number text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

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
    item_name text,
    size text,
    colour text,
    weight numeric(14,3),
    height numeric(14,3),
    width numeric(14,3),
    length numeric(14,3),
    attributes jsonb not null default '{}'::jsonb,
    pricing_mode text not null default 'price',
    discount_percent numeric(5,2) not null default 0,
    catalog_visible boolean not null default true,
    reorder_target numeric(14,3) not null default 0,
    reorder_enabled boolean not null default false,
    reorder_reminder_date date,
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
    attributes jsonb not null default '{}'::jsonb,
    pricing_mode text not null default 'inherit',
    discount_percent numeric(5,2) not null default 0,
    preferred_vendor_id uuid references parties(id),
    reorder_level numeric(14,3) not null default 0,
    reorder_target numeric(14,3) not null default 0,
    reorder_enabled boolean not null default false,
    reorder_reminder_date date,
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
    available_quantity numeric(14,3) not null default 0,
    availability text not null default 'UNKNOWN',
    lead_time_days integer not null default 0,
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

create table if not exists accounts (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    nickname text not null,
    account_type text not null,
    party_id uuid references parties(id),
    holder_name text,
    phone text,
    email text,
    opening_balance numeric(14,2) not null default 0,
    is_company_account boolean not null default false,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists account_transactions (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    from_account_id uuid references accounts(id),
    to_account_id uuid references accounts(id),
    amount numeric(14,2) not null check (amount > 0),
    payment_mode text,
    reference text,
    category text,
    description text,
    transaction_date date not null default current_date,
    source_type text,
    source_id uuid,
    reversal_of_transaction_id uuid references account_transactions(id),
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now(),
    check (from_account_id is not null or to_account_id is not null)
);

create table if not exists accounting_period_locks (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    period_start date not null,
    period_end date not null,
    reason text,
    closed_by text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    reopened_at timestamptz,
    reopened_by text,
    reopen_reason text,
    check (period_start <= period_end)
);

create table if not exists settlements (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    from_party_id uuid references parties(id),
    to_party_id uuid references parties(id),
    amount numeric(14,2) not null check (amount > 0),
    status text not null default 'PENDING' check (status in ('PENDING','PARTIAL','SETTLED','CANCELLED')),
    due_date date,
    settled_at timestamptz,
    notes text,
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists borrowings (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    party_id uuid not null references parties(id),
    direction text not null check (direction in ('borrow', 'repay')),
    amount numeric(14,2) not null check (amount > 0),
    transaction_date date not null default current_date,
    account_id uuid references accounts(id),
    reference text,
    notes text,
    created_at timestamptz not null default now()
);

create table if not exists invoice_sequences (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    year integer not null,
    month integer not null,
    last_number integer not null default 0,
    unique(company_id, year, month)
);

create table if not exists invoices (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    invoice_number text not null,
    customer_party_id uuid not null references parties(id),
    customer_gst text,
    document_data jsonb,
    invoice_date date not null default current_date,
    subtotal numeric(14,2) not null default 0,
    gst_total numeric(14,2) not null default 0,
    total numeric(14,2) not null default 0,
    payment_mode text,
    account_id uuid references accounts(id),
    reference text,
    status text not null default 'POSTED',
    collection_status text not null default 'UNPAID' check (collection_status in ('UNPAID','PARTIAL','SETTLED','BAD_DEBT')),
    amount_received numeric(14,2) not null default 0,
    due_date date,
    reminder_date date,
    bad_debt_reason text,
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now(),
    unique(company_id, invoice_number)
);

create table if not exists receivables (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    party_id uuid not null references parties(id),
    invoice_id uuid references invoices(id),
    reference text,
    amount_due numeric(14,2) not null check (amount_due > 0),
    amount_received numeric(14,2) not null default 0,
    status text not null default 'UNPAID' check (status in ('UNPAID','PARTIAL','SETTLED','BAD_DEBT')),
    due_date date,
    reminder_date date,
    last_reminded_at timestamptz,
    bad_debt_reason text,
    notes text,
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists receivable_payments (
    id uuid primary key default gen_random_uuid(),
    receivable_id uuid not null references receivables(id) on delete cascade,
    company_id uuid not null references companies(id),
    account_id uuid references accounts(id),
    amount numeric(14,2) not null check (amount > 0),
    payment_mode text not null,
    idempotency_key text,
    reference text,
    payment_date date not null default current_date,
    notes text,
    reversed_at timestamptz,
    reversed_by_transaction_id uuid references account_transactions(id),
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now()
);

create table if not exists receivable_reminders (
    id uuid primary key default gen_random_uuid(),
    receivable_id uuid not null references receivables(id) on delete cascade,
    company_id uuid not null references companies(id),
    reminder_date date,
    next_reminder_date date,
    reminded_at timestamptz not null default now(),
    reminded_by text,
    notes text
);

create table if not exists invoice_reconcile_runs (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    healed_count integer not null default 0,
    triggered_by text,
    created_at timestamptz not null default now()
);

create table if not exists invoice_items (
    id uuid primary key default gen_random_uuid(),
    invoice_id uuid not null references invoices(id) on delete cascade,
    product_id uuid not null references products(id),
    variant_id uuid references product_variants(id),
    portal_product_id text,
    quantity numeric(14,3) not null check (quantity > 0),
    selling_price numeric(14,2) not null,
    gst_rate numeric(6,2) not null default 0,
    gst_amount numeric(14,2) not null default 0,
    line_total numeric(14,2) not null
);

create table if not exists purchases (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    vendor_party_id uuid not null references parties(id),
    line_items jsonb not null default '[]'::jsonb,
    bill_number text,
    purchase_date date not null default current_date,
    subtotal numeric(14,2) not null default 0,
    gst_total numeric(14,2) not null default 0,
    total numeric(14,2) not null default 0,
    amount_paid numeric(14,2) not null default 0,
    payment_status text not null default 'UNPAID' check (payment_status in ('UNPAID','PARTIAL','PAID')),
    payment_mode text,
    account_id uuid references accounts(id),
    reference text,
    due_date date,
    notes text,
    receipt_type text not null default 'PRODUCT' check (receipt_type in ('PRODUCT','STOCK','SERVICE')),
    receipt_status text not null default 'PENDING' check (receipt_status in ('PENDING','RECEIVED')),
    received_at timestamptz,
    received_notes text,
    status text not null default 'POSTED',
    document_id uuid,
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now()
);

create table if not exists purchase_payments (
    id uuid primary key default gen_random_uuid(),
    purchase_id uuid not null references purchases(id) on delete cascade,
    company_id uuid not null references companies(id),
    account_id uuid not null references accounts(id),
    amount numeric(14,2) not null check (amount > 0),
    payment_mode text not null,
    idempotency_key text,
    reference text,
    payment_date date not null default current_date,
    notes text,
    reversed_at timestamptz,
    reversed_by_transaction_id uuid references account_transactions(id),
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now()
);

create table if not exists purchase_items (
    id uuid primary key default gen_random_uuid(),
    purchase_id uuid not null references purchases(id) on delete cascade,
    product_id uuid not null references products(id),
    variant_id uuid references product_variants(id),
    quantity numeric(14,3) not null check (quantity > 0),
    buying_price numeric(14,2) not null,
    gst_rate numeric(6,2) not null default 0,
    gst_amount numeric(14,2) not null default 0,
    line_total numeric(14,2) not null
);

create table if not exists expenses (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    party_id uuid references parties(id),
    expense_category text not null,
    description text,
    amount numeric(14,2) not null check (amount > 0),
    expense_date date not null default current_date,
    payment_mode text,
    account_id uuid references accounts(id),
    reference text,
    document_id uuid,
    created_by uuid references user_profiles(id),
    created_at timestamptz not null default now()
);

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

create index if not exists idx_parties_company on parties(company_id);
create index if not exists idx_products_company on products(company_id);
create index if not exists idx_vendor_contributions_vendor on vendor_contributions(vendor_id);
create index if not exists idx_vendor_contributions_product on vendor_contributions(product_id);
create index if not exists idx_stock_movements_product on stock_movements(product_id);
create index if not exists idx_account_transactions_company on account_transactions(company_id);
create index if not exists idx_account_transactions_company_date on account_transactions(company_id, transaction_date desc, created_at desc);
create index if not exists idx_account_transactions_company_category_source on account_transactions(company_id, category, source_type);
create unique index if not exists uq_account_transactions_reversal_once on account_transactions(company_id, reversal_of_transaction_id) where reversal_of_transaction_id is not null;
create unique index if not exists uq_accounts_one_company_account on accounts(company_id) where is_company_account = true;
create index if not exists idx_period_locks_company_dates on accounting_period_locks(company_id, period_start, period_end);
create index if not exists idx_period_locks_active on accounting_period_locks(company_id, is_active);
create index if not exists idx_borrowings_company_date on borrowings(company_id, transaction_date desc);
create index if not exists idx_borrowings_party_date on borrowings(party_id, transaction_date desc);
create index if not exists idx_invoices_customer on invoices(customer_party_id);
create index if not exists idx_receivables_company_status_due on receivables(company_id, status, due_date);
create index if not exists idx_receivables_party on receivables(party_id);
create index if not exists idx_receivable_payments_receivable on receivable_payments(receivable_id);
create index if not exists idx_purchase_payments_purchase on purchase_payments(purchase_id, payment_date desc, created_at desc);
create index if not exists idx_receivable_reminders_receivable on receivable_reminders(receivable_id, reminded_at desc);
create index if not exists idx_invoice_reconcile_runs_company_date on invoice_reconcile_runs(company_id, created_at desc);
create index if not exists idx_purchases_vendor on purchases(vendor_party_id);
create index if not exists idx_purchases_company_date on purchases(company_id, purchase_date desc, created_at desc);
create index if not exists idx_purchases_receipt_status on purchases(company_id, receipt_status, receipt_type);
create index if not exists idx_audit_entity on audit_events(entity_type, entity_id);
create index if not exists idx_document_links_entity on document_links(entity_type, entity_id);
create index if not exists idx_variants_product_active on product_variants(product_id, is_active);
create index if not exists idx_vendor_offers_product on vendor_contributions(product_id, variant_id, vendor_id);
create index if not exists idx_stock_balances_item on stock_balances(company_id, product_id, variant_id);
