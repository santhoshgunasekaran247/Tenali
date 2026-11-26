"""Allow metering of embedded catalog images."""
from alembic import op

revision = "067_ai_catalog_images"
down_revision = "066_brand_image"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table ai_attachments drop constraint ai_attachments_input_bound_check;
        alter table ai_attachments add constraint ai_attachments_input_bound_check
            check(input_bound between 1 and 140512);
        alter table ai_attachments drop constraint ai_attachments_mime_type_check;
        alter table ai_attachments add constraint ai_attachments_mime_type_check
            check(mime_type in ('text/plain','image/jpeg','image/png'));
    """)


def downgrade():
    op.execute("""
        do $$ begin
            if exists(select 1 from ai_attachments where input_bound > 16000 or mime_type='image/png') then
                raise exception 'Remove AI attachments with embedded images or transparent PNGs before downgrading';
            end if;
        end $$;
        alter table ai_attachments drop constraint ai_attachments_input_bound_check;
        alter table ai_attachments add constraint ai_attachments_input_bound_check
            check(input_bound between 1 and 16000);
        alter table ai_attachments drop constraint ai_attachments_mime_type_check;
        alter table ai_attachments add constraint ai_attachments_mime_type_check
            check(mime_type in ('text/plain','image/jpeg'));
    """)
