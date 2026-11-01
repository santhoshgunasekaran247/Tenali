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
