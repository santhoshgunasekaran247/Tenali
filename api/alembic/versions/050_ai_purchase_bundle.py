"""Add the compound AI purchase workflow action."""
from alembic import op

revision = "050_ai_purchase_bundle"
down_revision = "049_ai_operations"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("insert into ai_action_controls(key) values ('purchase_bundle_create') on conflict(key) do nothing")


def downgrade():
    op.execute("""
        do $$ begin
            if exists(select 1 from ai_executions e join ai_action_drafts d on d.id=e.draft_id
                where d.action_key='purchase_bundle_create') then
                raise exception 'Cannot downgrade an executed purchase bundle; preserve its business audit history';
            end if;
        end $$;
        delete from ai_tenant_action_controls where action_key='purchase_bundle_create';
        update ai_action_drafts set status='discarded',payload='{}',validation=null,
            approved_version=null,approved_at=null,version=version+1 where action_key='purchase_bundle_create';
        delete from ai_action_controls where key='purchase_bundle_create';
    """)