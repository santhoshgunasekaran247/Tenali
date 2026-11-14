"""Borrowings also record money lent to a party ('lend') and collected back ('collect')."""
from alembic import op

revision = "052_borrowing_lending"
down_revision = "051_ai_operation_workflows"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table borrowings drop constraint if exists borrowings_direction_check;
        alter table borrowings add constraint borrowings_direction_check
            check (direction in ('borrow','repay','lend','collect'));
    """)


def downgrade():
    op.execute("""
        alter table borrowings drop constraint if exists borrowings_direction_check;
        alter table borrowings add constraint borrowings_direction_check check (direction in ('borrow','repay'));
    """)
