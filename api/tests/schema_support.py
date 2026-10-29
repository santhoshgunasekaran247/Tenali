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
