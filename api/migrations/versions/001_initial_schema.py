"""SRU Global initial schema.

Revision ID: 001_initial_schema
Revises:
"""

from pathlib import Path
from alembic import op

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[3] / "database" / "schema.sql"
    op.get_bind().exec_driver_sql(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError(
        "The initial schema is not automatically downgraded. "
        "Create a new migration for intentional schema changes."
    )
