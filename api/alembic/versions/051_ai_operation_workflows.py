"""Persistent private Operations workflow plans; business approvals stay unchanged."""
from alembic import op

revision = "051_ai_operation_workflows"
down_revision = "050_ai_purchase_bundle"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table ai_operation_workflows (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null,
            user_id uuid not null,
            conversation_id uuid not null,
            client_key uuid not null,
            action_key text not null references ai_action_controls(key),
            request_hash text not null,
            plan jsonb not null,
            status text not null default 'active' check(status in ('active','completed','discarded')),
            version integer not null default 1 check(version>0),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            expires_at timestamptz not null,
            unique(company_id,user_id,conversation_id,client_key),
            foreign key(company_id,user_id,conversation_id) references ai_conversations(company_id,user_id,id),
            check(octet_length(plan::text)<=200000)
        );
        create index ai_workflow_history on ai_operation_workflows(company_id,user_id,conversation_id,created_at,id);
        alter table ai_operation_workflows enable row level security;
        create policy ai_workflow_private on ai_operation_workflows to tenali_runtime
            using(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid)
            with check(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid);
        grant select,insert,update on ai_operation_workflows to tenali_runtime;
    """)


def downgrade():
    op.execute("drop table ai_operation_workflows")
