"""Tenant-owned Supabase object references; existing bytes migrate separately."""
from alembic import op

revision = "031_object_storage"
down_revision = "030_supabase_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table stored_files (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null references companies(id),
            bucket text not null check(bucket in ('tenali-public','tenali-private')),
            file_kind text not null check(file_kind in ('image','signature','document')),
            object_path text not null,
            mime_type text not null,
            file_size bigint not null check(file_size > 0),
            sha256 text not null,
            created_at timestamptz not null default now(),
            unique(company_id,bucket,file_kind,sha256),
            unique(bucket,object_path)
        );
        alter table stored_files enable row level security;
        create policy tenali_company_scope on stored_files to tenali_runtime
            using(company_id=tenali_current_company()) with check(company_id=tenali_current_company());
        grant select,insert on stored_files to tenali_runtime;
        alter table documents add column stored_file_id uuid references stored_files(id);
        create index ix_document_stored_file on documents(stored_file_id);
    """)


def downgrade():
    raise NotImplementedError("Stored file references must be preserved")
