"""Let each workspace turn the Operations Portal "next step" workflow messages on or off."""
from alembic import op

revision = "040_workflow_guidance"
down_revision = "039_refund_settlements"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table companies add column workflow_guidance_enabled boolean not null default true")


def downgrade():
    op.execute("alter table companies drop column workflow_guidance_enabled")
