"""Persist resumable tenant-private bulk imports."""
from alembic import op

revision = "068_bulk_import_jobs"
down_revision = "067_ai_catalog_images"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table bulk_import_jobs (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null,
            user_id uuid not null,
            client_key uuid not null,
            kind text not null check(kind in ('products','variants','hsn','parties','brands','categories','images')),
            input_hash text not null,
            content bytea not null check(octet_length(content)<=20971520),
            rows jsonb not null check(jsonb_typeof(rows)='array' and jsonb_array_length(rows) between 1 and 2000),
            outcomes jsonb not null default '[]'::jsonb check(jsonb_typeof(outcomes)='array'),
            next_row integer not null default 0,
            created_at timestamptz not null default now(),
            expires_at timestamptz not null default now()+interval '7 days',
            unique(company_id,user_id,client_key),
            check(next_row between 0 and jsonb_array_length(rows)),
            check(next_row=jsonb_array_length(outcomes))
        );
        create index bulk_import_jobs_user on bulk_import_jobs(company_id,user_id,created_at desc);
        alter table bulk_import_jobs enable row level security;
        create policy bulk_jobs_private on bulk_import_jobs to tenali_runtime
            using(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid)
            with check(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid);
        grant select,insert,update,delete on bulk_import_jobs to tenali_runtime;
    """)


def downgrade():
    op.execute("drop table bulk_import_jobs")
