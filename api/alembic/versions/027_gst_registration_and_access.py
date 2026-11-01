"""GST-unregistered tenants and store/module-level access for team members."""

from alembic import op

revision = "027_gst_registration_and_access"
down_revision = "026_checkout_policy_grant"
branch_labels = None
depends_on = None

MODULES = ("billing", "purchases", "inventory", "receivables", "accounts", "settlements", "reports", "parties", "masters", "orders")


def upgrade():
    op.execute(
        f"""
        alter table companies add column if not exists gst_registered boolean not null default true;
        -- null = all stores / all modules (owners and administrators always have everything)
        alter table tenant_memberships add column if not exists store_ids uuid[];
        alter table tenant_memberships add column if not exists modules text[]
            check (modules is null or modules <@ array[{", ".join(f"'{m}'" for m in MODULES)}]::text[]);
        """
    )


def downgrade():
    op.execute(
        """
        alter table tenant_memberships drop column if exists modules;
        alter table tenant_memberships drop column if exists store_ids;
        alter table companies drop column if exists gst_registered;
        """
    )
