"""Permit competing unverified claims; only verified domains are globally exclusive."""

from alembic import op

revision="015_domain_claims"
down_revision="014_multi_tenant"
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""
        alter table tenant_domains drop constraint tenant_domains_hostname_key;
        alter table tenant_domains add constraint uq_tenant_domain_claim unique(company_id,hostname);
        create unique index uq_tenant_verified_hostname on tenant_domains(hostname) where verified_at is not null;
    """)


def downgrade():
    raise NotImplementedError("Verified domain ownership history must be retained")