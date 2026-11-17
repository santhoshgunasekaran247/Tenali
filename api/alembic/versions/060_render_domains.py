"""Persistent, tenant-owned Render domain provisioning."""

from alembic import op

revision = "060_render_domains"
down_revision = "059_self_shipping"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table tenant_domains
            add column hosting_status text not null default 'manual'
                check (hosting_status in ('manual','dns_pending','provisioning','tls_pending','active','error','removing')),
            add column hosting_error text,
            add column next_check_at timestamptz not null default now();
        create table tenant_domain_bindings (
            hostname text primary key,
            domain_id uuid not null references tenant_domains(id) on delete cascade,
            kind text not null check (kind in ('web','api','alias')),
            render_id text,
            provider_owned boolean not null default false
        );
        create index ix_domain_bindings_domain on tenant_domain_bindings(domain_id);
        insert into tenant_domain_bindings(hostname,domain_id,kind)
            select hostname,id,'web' from tenant_domains where verified_at is not null;
        revoke all on tenant_domain_bindings from public,tenali_runtime;
        create table tenant_social_relays (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            hostname text not null,
            key_hash text not null,
            result_ciphertext text,
            expires_at timestamptz not null default now()+interval '3 minutes'
        );
        create index ix_social_relays_expiry on tenant_social_relays(expires_at);
        revoke all on tenant_social_relays from public,tenali_runtime;
        create index ix_domain_provisioning_due on tenant_domains(next_check_at)
            where hosting_status not in ('manual','active');
    """)


def downgrade():
    op.execute("""
        drop table tenant_social_relays;
        drop table tenant_domain_bindings;
        drop index ix_domain_provisioning_due;
        alter table tenant_domains drop column hosting_status,
            drop column hosting_error, drop column next_check_at;
    """)
