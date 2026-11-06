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
