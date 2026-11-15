"""Register the opt-in quotation workflow action."""
from alembic import op

revision = "058_ai_quotation"
down_revision = "057_invoice_sequence_bigint"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("insert into ai_action_controls(key) values ('quotation_create') on conflict(key) do nothing")


def downgrade():
    op.execute("""do $$ begin
        if exists(select 1 from ai_executions e join ai_action_drafts d on d.id=e.draft_id
            where d.action_key='quotation_create') then
            raise exception 'Cannot downgrade executed quotation workflows';
        end if;
        end $$;
        update ai_action_drafts set status='discarded',payload='{}',validation=null,
            approved_version=null,approved_at=null,version=version+1 where action_key='quotation_create';
        update ai_action_controls set enabled=false,execution_enabled=false,fingerprint='',version=version+1
            where key='quotation_create';
    """)
