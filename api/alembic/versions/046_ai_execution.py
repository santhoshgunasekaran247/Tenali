"""Atomic approved business execution and private outcome recovery."""
from alembic import op

revision = "046_ai_execution"
down_revision = "045_ai_action_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table ai_action_controls add column execution_enabled boolean not null default false;
        alter table stock_transfers add column created_by_user_id uuid;
        create function tenali_stock_transfer_actor() returns trigger
            language plpgsql security definer set search_path=public,pg_temp as $$
        begin
            if new.created_by_user_id is not null and (
                new.created_by_user_id is distinct from nullif(current_setting('app.actor_user_id',true),'')::uuid
                or not exists(select 1 from tenant_users u join tenant_memberships m on m.user_id=u.id and m.company_id=u.company_id
                    where u.id=new.created_by_user_id and u.company_id=new.company_id and u.is_active and m.is_active)) then
                raise exception 'Stock transfer actor does not belong to the active workspace' using errcode='23514';
            end if;
            return new;
        end $$;
        revoke all on function tenali_stock_transfer_actor() from public;
        create trigger tenali_stock_transfer_actor before insert or update on stock_transfers
            for each row execute function tenali_stock_transfer_actor();
        insert into ai_action_controls(key) values
            ('invoice_cancel'),('purchase_cancel'),('product_delete'),('transaction_delete')
            on conflict(key) do nothing;
        alter table ai_action_drafts drop constraint ai_action_drafts_status_check;
        alter table ai_action_drafts add constraint ai_action_drafts_status_check
            check(status in ('editing','validated','approved','discarded','executed'));
        create table ai_executions (
            id uuid primary key,
            company_id uuid not null,
            user_id uuid not null,
            conversation_id uuid not null,
            draft_id uuid not null,
            draft_version integer not null,
            payload_hash text not null,
            request_key text not null,
            status text not null check(status in ('succeeded','failed')),
            result jsonb not null,
            created_at timestamptz not null default now(),
            unique(draft_id,draft_version),
            unique(company_id,request_key),
            foreign key(company_id,user_id,conversation_id,draft_id)
                references ai_action_drafts(company_id,user_id,conversation_id,id)
        );
        alter table ai_executions enable row level security;
        create policy ai_execution_private on ai_executions to tenali_runtime
            using(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid)
            with check(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid);
        grant select,insert on ai_executions to tenali_runtime;
    """)


def downgrade():
    op.execute("""
        drop table ai_executions;
        update ai_action_drafts set status='discarded',payload='{}',validation=null,
            approved_version=null,approved_at=null,version=version+1 where status='executed';
        alter table ai_action_drafts drop constraint ai_action_drafts_status_check;
        alter table ai_action_drafts add constraint ai_action_drafts_status_check
            check(status in ('editing','validated','approved','discarded'));
        alter table ai_action_controls drop column execution_enabled;
        drop trigger tenali_stock_transfer_actor on stock_transfers;
        drop function tenali_stock_transfer_actor();
        alter table stock_transfers drop column created_by_user_id;
    """)
