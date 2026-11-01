"""Let the tenant runtime role read checkout policy columns (never credentials) for order fulfilment."""

from alembic import op

revision = "026_checkout_policy_grant"
down_revision = "025_online_channel"
branch_labels = None
depends_on = None

POLICY_COLUMNS = (
    "company_id, enabled, shipping_paise, pickup_location, prepaid_enabled, shipping_sac, shipping_gst_rate, cod_enabled, "
    "cod_limit, cod_approval_hours, cod_overdue_days, cod_serviceable_pincodes, pickup_enabled, pickup_hold_hours, "
    "pickup_reminder_hours, prepaid_hold_minutes, updated_at"
)


def upgrade():
    op.execute(f"grant select ({POLICY_COLUMNS}) on checkout_settings to tenali_runtime")


def downgrade():
    op.execute("revoke select on checkout_settings from tenali_runtime")
