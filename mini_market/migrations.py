"""Apply versioned migrations without dropping existing application data."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, event


def upgrade(database_url, revision="head"):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
    engine = create_engine(database_url)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def disable_driver_transaction_control(connection, record):
            connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def begin_sqlite_transaction(connection):
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            tables = set(inspect(connection).get_table_names())
            if "alembic_version" not in tables and "products" in tables:
                # Adopt the original three-table SQLite prototype, then upgrade it.
                expected = {
                    "products": {"id", "name", "description", "category", "price_cents", "stock", "illustration", "initials"},
                    "orders": {"id", "reference", "checkout_key", "total_cents", "created_at"},
                    "order_items": {"id", "order_id", "product_id", "product_name", "unit_price_cents", "quantity"},
                }
                inspector = inspect(connection)
                if tables != set(expected) or any(
                    {column["name"] for column in inspector.get_columns(table)} != columns
                    for table, columns in expected.items()
                ):
                    raise RuntimeError("Unrecognised legacy schema; migration stopped without changes.")
                command.stamp(config, "0001")
            command.upgrade(config, revision)
    finally:
        engine.dispose()
