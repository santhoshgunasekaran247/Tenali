"""Shared social-login settings and federated workspace owners."""
from alembic import op

revision = "029_workspace_federation"
down_revision = "028_customer_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table platform_auth_settings(
            id boolean primary key default true check(id),
            project_id text not null,api_key text not null,auth_domain text not null,
            providers text[] not null,enabled boolean not null default false,
            updated_at timestamptz not null default now()
        );
        revoke all on platform_auth_settings from tenali_runtime;
        alter table tenant_users add column firebase_uid text;
        create unique index uq_workspace_firebase on tenant_users(company_id,firebase_uid);
        alter table tenant_users alter column password_hash drop not null;
    """)


def downgrade():
    raise NotImplementedError("Federated workspace identities must be preserved")
