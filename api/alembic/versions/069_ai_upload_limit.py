"""Allow larger AI documents while keeping normalized image storage bounded."""
from alembic import op

revision = "069_ai_upload_limit"
down_revision = "068_bulk_import_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table ai_attachments drop constraint ai_attachments_content_check;
        alter table ai_attachments add constraint ai_attachments_content_check
            check(octet_length(content)<=case when mime_type='text/plain' then 20971520 else 2097152 end);
    """)


def downgrade():
    op.execute("""
        do $$ begin
            if exists(select 1 from ai_attachments where octet_length(content)>2097152) then
                raise exception 'Remove AI attachments larger than 2 MiB before downgrading';
            end if;
        end $$;
        alter table ai_attachments drop constraint ai_attachments_content_check;
        alter table ai_attachments add constraint ai_attachments_content_check
            check(octet_length(content)<=2097152);
    """)
