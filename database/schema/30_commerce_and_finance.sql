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
