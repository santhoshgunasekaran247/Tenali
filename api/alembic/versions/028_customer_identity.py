"""Federated shopper contacts kept separate from counter customer records."""

from alembic import op

revision = "028_customer_identity"
down_revision = "027_gst_registration_and_access"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table parties add column phone_normalized text;
        update parties set phone_normalized = case
            when regexp_replace(phone, '[^0-9]', '', 'g') ~ '^[6-9][0-9]{9}$'
                then '+91' || regexp_replace(phone, '[^0-9]', '', 'g')
            when regexp_replace(phone, '[^0-9]', '', 'g') ~ '^91[6-9][0-9]{9}$'
                then '+' || regexp_replace(phone, '[^0-9]', '', 'g')
            when trim(phone) ~ '^\\+[1-9][0-9]{7,14}$' then trim(phone)
            else null end where phone is not null;
        create index ix_party_phone_contact on parties(company_id,phone_normalized);
        alter table shopper_accounts alter column password_hash drop not null;
        alter table shopper_accounts add column firebase_uid text;
        alter table shopper_accounts add column phone text;
        alter table shopper_accounts add column customer_party_id uuid;
        alter table shopper_accounts add column linked_by uuid references tenant_users(id);
        alter table shopper_accounts add column linked_at timestamptz;
        create unique index uq_shopper_firebase on shopper_accounts(company_id,firebase_uid);
        create unique index uq_shopper_customer on shopper_accounts(company_id,customer_party_id);
        create unique index uq_party_company_identity on parties(company_id,id);
        alter table shopper_accounts add constraint fk_shopper_customer
            foreign key(company_id,customer_party_id) references parties(company_id,id);
        grant select(id,company_id,customer_party_id) on shopper_accounts to tenali_runtime;
    """)


def downgrade():
    raise NotImplementedError("Customer identity links must be preserved")
