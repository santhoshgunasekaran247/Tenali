"""Persist legacy runtime schema before disabling request-time DDL."""

from alembic import op

revision="013_runtime_schema"
down_revision="012_operational_audit"
branch_labels=None
depends_on=None


def upgrade():
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from app.services.accounts_service import AccountsService
    from app.services.billing_service import BillingService
    from app.services.collections_service import CollectionsService
    from app.services.purchases_service import PurchasesService
    from app.services.settlements_service import SettlementsService
    from app.services.period_lock_service import ensure_period_locks_table
    connection=op.get_bind()
    connection.info.pop('tenali_managed_schema',None)
    accounts=AccountsService(connection)
    accounts._ensure_account_extensions()
    accounts._ensure_borrowings_table()
    accounts._ensure_transaction_extensions()
    BillingService(connection)._ensure_tables()
    CollectionsService(connection)._ensure_tables()
    PurchasesService(connection)._ensure_tables()
    SettlementsService(connection)._ensure_table()
    ensure_period_locks_table(connection)


def downgrade():
    raise NotImplementedError("Operational schema must be retained")