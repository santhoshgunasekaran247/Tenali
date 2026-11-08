"""Private operational drafts and explicit version-bound approval; no execution."""
from alembic import op

revision = "045_ai_action_drafts"
down_revision = "044_ai_business_reads"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table ai_action_controls (
            key text primary key,
            enabled boolean not null default false,
            fingerprint text not null default '',
            version integer not null default 1 check(version>0),
            updated_by uuid references platform_admins(id),
            updated_at timestamptz not null default now()
        );
        insert into ai_action_controls(key) values
            ('expense_create'),('purchase_create'),('invoice_create'),('party_create'),('party_update'),
            ('product_create'),('product_update'),('stock_adjust'),('stock_transfer'),
            ('purchase_payment'),('collection_payment');
        create table ai_tenant_action_controls (
            company_id uuid not null references companies(id),
            action_key text not null references ai_action_controls(key),
            allowed boolean not null default false,
            version integer not null default 1 check(version>0),
            updated_by uuid references platform_admins(id),
            updated_at timestamptz not null default now(),
            primary key(company_id,action_key)
        );
        create table ai_action_drafts (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null,
            user_id uuid not null,
            conversation_id uuid not null,
            client_key uuid not null,
            action_key text not null references ai_action_controls(key),
            target_id uuid,
            payload jsonb not null,
            payload_hash text not null,
            request_hash text not null,
            validation jsonb,
            status text not null default 'editing' check(status in ('editing','validated','approved','discarded')),
            version integer not null default 1 check(version>0),
            approved_version integer,
            approved_at timestamptz,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            expires_at timestamptz not null,
            unique(company_id,user_id,conversation_id,client_key),
            unique(company_id,user_id,conversation_id,id),
            foreign key(company_id,user_id,conversation_id) references ai_conversations(company_id,user_id,id),
            check(octet_length(payload::text)<=20000)
        );
        create index ai_draft_history on ai_action_drafts(company_id,user_id,conversation_id,created_at,id);
        alter table ai_action_controls enable row level security;
        create policy ai_action_read on ai_action_controls for select to tenali_runtime using(true);
        grant select on ai_action_controls to tenali_runtime;
        alter table ai_tenant_action_controls enable row level security;
        create policy ai_tenant_action_read on ai_tenant_action_controls for select to tenali_runtime
            using(company_id=tenali_current_company());
        grant select on ai_tenant_action_controls to tenali_runtime;
        alter table ai_action_drafts enable row level security;
        create policy ai_draft_private on ai_action_drafts to tenali_runtime
            using(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid)
            with check(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid);
        grant select,insert,update on ai_action_drafts to tenali_runtime;
    """)
    op.execute("""
        create table ai_draft_approvals (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null,
            user_id uuid not null,
            conversation_id uuid not null,
            draft_id uuid not null,
            draft_version integer not null check(draft_version>0),
            payload_hash text not null,
            contract_fingerprint text not null,
            snapshot_hash text not null,
            approved_at timestamptz not null default now(),
            unique(draft_id,draft_version),
            foreign key(company_id,user_id,conversation_id,draft_id)
                references ai_action_drafts(company_id,user_id,conversation_id,id)
        );
        alter table ai_draft_approvals enable row level security;
        create policy ai_approval_private on ai_draft_approvals to tenali_runtime
            using(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid)
            with check(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid);
        grant select,insert on ai_draft_approvals to tenali_runtime;
    """)


def downgrade():
    op.execute("drop table ai_draft_approvals; drop table ai_action_drafts; drop table ai_tenant_action_controls; drop table ai_action_controls;")
