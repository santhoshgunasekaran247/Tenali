"""Replace Firebase authentication without reassigning existing identities."""
from alembic import op

revision = "030_supabase_auth"
down_revision = "029_workspace_federation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        do $$ begin
            if exists(select 1 from shopper_accounts where firebase_uid is not null)
                or exists(select 1 from tenant_users where firebase_uid is not null) then
                raise exception 'Existing Firebase identities require an explicit identity migration before switching to Supabase';
            end if;
        end $$;
        alter table shopper_accounts add column supabase_uid text;
        alter table tenant_users add column supabase_uid text;
        create unique index uq_shopper_supabase on shopper_accounts(company_id,supabase_uid);
        create unique index uq_workspace_supabase on tenant_users(company_id,supabase_uid);
        alter table platform_auth_settings rename column project_id to supabase_url;
        alter table platform_auth_settings rename column api_key to public_key;
        alter table platform_auth_settings drop column auth_domain;
        update platform_auth_settings set supabase_url='',public_key='',
            providers=array['google','facebook'],enabled=false,updated_at=now();
    """)


def downgrade():
    raise NotImplementedError("Supabase identities must be preserved")
