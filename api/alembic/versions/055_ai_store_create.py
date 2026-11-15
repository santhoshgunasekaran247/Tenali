"""Opt-in AI workflow step for creating a store."""
from alembic import op

revision = "055_ai_store_create"
down_revision = "054_product_image_originals"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("insert into ai_action_controls(key) values ('store_create') on conflict(key) do nothing")


def downgrade():
    op.execute("""do $$ begin
        if exists(select 1 from ai_executions e join ai_action_drafts d on d.id=e.draft_id
            where d.action_key='store_create') then
            raise exception 'Cannot downgrade executed store workflows; preserve private outcomes and business audit history';
        end if;
        end $$;
        update ai_action_drafts set status='discarded',payload='{}',validation=null,
            approved_version=null,approved_at=null,version=version+1 where action_key='store_create';
        update ai_action_controls set enabled=false,execution_enabled=false,fingerprint='',version=version+1
            where key='store_create';
    """)
