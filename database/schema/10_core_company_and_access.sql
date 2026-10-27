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
