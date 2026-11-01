"""Enforce tenant ownership of document storage references in the database."""
from alembic import op

revision = "032_document_storage_scope"
down_revision = "031_object_storage"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table stored_files add constraint uq_stored_file_company unique(company_id,id);
        alter table documents add constraint fk_document_stored_file_company
            foreign key(company_id,stored_file_id) references stored_files(company_id,id);
    """)


def downgrade():
    op.drop_constraint("fk_document_stored_file_company", "documents", type_="foreignkey")
    op.drop_constraint("uq_stored_file_company", "stored_files", type_="unique")
