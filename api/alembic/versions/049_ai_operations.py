"""Opt-in coverage of remaining Operations workflows and private reports."""
from alembic import op

revision = "049_ai_operations"
down_revision = "048_ai_voice"
branch_labels = None
depends_on = None

ACTION_KEYS = (
    "account_create", "account_update", "account_transaction_create", "account_transaction_reverse",
    "borrowing_create", "refund_settle", "receivable_create", "receivable_status", "receivable_reminder",
    "purchase_receive", "product_confirm", "product_merge", "variant_create", "variant_update",
    "offer_create", "offer_update", "vendor_bulk_map", "brand_create", "brand_update",
    "category_create", "category_update", "reorder_reminder", "stock_transfer_reverse", "movement_attribute",
    "report_export", "gst_reconcile", "business_payment_create",
)
READ_KEYS = ("borrowing_entries", "stock_transfers", "stock_movements", "movement_sources", "variants",
             "vendor_offers", "collection_reminders", "reminder_history", "account_journal", "audit_events", "product_details", "business_payments")


def upgrade():
    op.execute("insert into ai_action_controls(key) values " +
               ",".join(f"('{key}')" for key in ACTION_KEYS) + " on conflict(key) do nothing")
    op.execute("insert into ai_capabilities(key) values " +
               ",".join(f"('{key}')" for key in READ_KEYS) + " on conflict(key) do nothing")
    op.execute("""
        grant update(lines) on stock_transfers to tenali_runtime;
        alter table ai_executions add constraint ai_execution_private_identity unique(company_id,user_id,id);
        create table ai_report_files (
            id uuid primary key,
            company_id uuid not null,
            user_id uuid not null,
            kind text not null check(kind in ('account_transactions','account_journal','sales_register',
                'purchase_register','ar_aging','ap_aging','gst_reconcile')),
            file_name text not null,
            content bytea check(octet_length(content)<=5000000),
            expires_at timestamptz not null,
            created_at timestamptz not null default now(),
            foreign key(company_id,user_id,id) references ai_executions(company_id,user_id,id) deferrable initially deferred,
            foreign key(company_id,user_id) references tenant_users(company_id,id)
        );
        alter table ai_report_files enable row level security;
        create policy ai_report_private on ai_report_files to tenali_runtime
            using(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid)
            with check(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid);
        grant select,insert,update on ai_report_files to tenali_runtime;
    """)


def downgrade():
    actions = ",".join(f"'{key}'" for key in ACTION_KEYS)
    reads = ",".join(f"'{key}'" for key in READ_KEYS)
    op.execute(f"""do $$ begin
        if exists(select 1 from ai_executions e join ai_action_drafts d on d.id=e.draft_id
            where d.action_key in ({actions})) then
            raise exception 'Cannot downgrade executed Operations workflows; preserve private outcomes and business audit history';
        end if;
        end $$;
        drop table ai_report_files;
        revoke update(lines) on stock_transfers from tenali_runtime;
        alter table ai_executions drop constraint ai_execution_private_identity;
        update ai_action_drafts set status='discarded',payload='{{}}',validation=null,
            approved_version=null,approved_at=null,version=version+1 where action_key in ({actions});
        update ai_action_controls set enabled=false,execution_enabled=false,fingerprint='',version=version+1
            where key in ({actions});
        update ai_capabilities set enabled=false,schema_fingerprint='',version=version+1 where key in ({reads});
    """)
