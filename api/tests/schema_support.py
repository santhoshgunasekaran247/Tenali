from pathlib import Path
import runpy

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect


def apply_customer_migration(connection, prepare=None):
    if "company_id" in {column["name"] for column in inspect(connection).get_columns("tenant_users")}:
        return
    if prepare:
        prepare()
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "018_customer_accounts.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()


def apply_product_minimum_migration(connection):
    if "minimum_order_quantity" in {column["name"] for column in inspect(connection).get_columns("products")}:
        return
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "019_product_minimum_order.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()


def ensure_default_store(db, company_id: str, code: str = "MAIN") -> str:
    """Test companies are inserted directly, so give them the default store the migration gives real ones."""
    from sqlalchemy import text

    row = db.execute(text("""insert into stores(company_id, code, name, kind, holds_stock, is_default, state_code)
        values(:company, :code, 'Main store', 'offline', true, true, '33') returning id"""),
        {"company": company_id, "code": code}).scalar_one()
    return str(row)


def apply_invoice_store_code_migration(connection):
    if "invoice_code" in {column["name"] for column in inspect(connection).get_columns("stores")}:
        return
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "035_invoice_store_codes.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()


def apply_storefront_enabled_migration(connection):
    if "storefront_enabled" in {column["name"] for column in inspect(connection).get_columns("companies")}:
        return
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "036_storefront_enabled.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()


def apply_product_draft_migration(connection):
    if "is_draft" in {column["name"] for column in inspect(connection).get_columns("products")}:
        return
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "037_product_drafts.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()


def apply_transaction_deletion_migration(connection):
    if inspect(connection).has_table("transaction_deletions"):
        return
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "038_transaction_deletions.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()


def apply_refund_settlement_migration(connection):
    apply_transaction_deletion_migration(connection)
    if inspect(connection).has_table("refund_settlements"):
        return
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "039_refund_settlements.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()


def apply_inventory_deletion_migration(connection):
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "033_inventory_product_deletion.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()


def apply_feature_controls_migration(connection):
    if inspect(connection).has_table("tenant_feature_controls"):
        return
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "041_ai_feature_controls.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()


def apply_ai_conversations_migration(connection):
    apply_feature_controls_migration(connection)
    if inspect(connection).has_table("ai_conversations"):
        return
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "042_ai_conversations.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()


def apply_ai_read_migration(connection):
    apply_ai_conversations_migration(connection)
    if not inspect(connection).has_table("ai_capabilities"):
        migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "043_ai_read_capabilities.py"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
    apply_ai_draft_migration(connection)


def apply_ai_draft_migration(connection):
    if not inspect(connection).has_table("ai_action_drafts"):
        migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "045_ai_action_drafts.py"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
    if not inspect(connection).has_table("ai_executions"):
        migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "046_ai_execution.py"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
    if not inspect(connection).has_table("ai_attachments"):
        migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "047_ai_private_media.py"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
    if not inspect(connection).has_table("ai_voice_requests"):
        migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "048_ai_voice.py"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
    if not inspect(connection).has_table("ai_report_files"):
        migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "049_ai_operations.py"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
    from sqlalchemy import text
    if not connection.execute(text("select 1 from ai_action_controls where key='purchase_bundle_create'")).first():
        migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "050_ai_purchase_bundle.py"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
    if not inspect(connection).has_table("ai_operation_workflows"):
        migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "051_ai_operation_workflows.py"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()


def apply_ai_business_read_migration(connection):
    from sqlalchemy import text
    apply_ai_read_migration(connection)
    if connection.execute(text("select 1 from ai_capabilities where key='accounts'")).first():
        return
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "044_ai_business_reads.py"))
    with Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()
