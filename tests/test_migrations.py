from pathlib import Path
import sqlite3
import pytest

from mini_market.db import connect, database_url
from mini_market.migrations import upgrade


def test_upgrade_is_repeatable_and_preserves_current_data(app, database):
    before = [dict(row) for row in database.execute("SELECT * FROM products ORDER BY id").fetchall()]
    upgrade(database_url(app.config["DATABASE"]))
    upgrade(database_url(app.config["DATABASE"]))
    assert [dict(row) for row in database.execute("SELECT * FROM products ORDER BY id").fetchall()] == before
    assert database.execute("SELECT version_num FROM alembic_version").fetchone()["version_num"] == "0002"


def test_original_sqlite_database_upgrade_preserves_receipts(tmp_path):
    path = tmp_path / "legacy.sqlite"
    original = sqlite3.connect(path)
    original.executescript(Path("tests/fixtures/legacy_schema.sql").read_text())
    original.execute("INSERT INTO products VALUES (1, 'Original', 'Description', 'Home', 500, 3, 'mug', 'O')")
    original.execute("INSERT INTO orders (id, reference, checkout_key, total_cents) VALUES (1, 'MM-OLD', 'old-key', 500)")
    original.execute("INSERT INTO order_items VALUES (1, 1, 1, 'Original', 500, 1)")
    original.commit()
    original.close()
    upgrade(database_url(path))
    current = connect(path)
    try:
        assert current.execute("SELECT reference FROM orders").fetchone()[0] == "MM-OLD"
        assert current.execute("SELECT stock FROM products").fetchone()[0] == 3
        assert current.execute("SELECT quantity FROM order_items").fetchone()[0] == 1
        assert current.execute("SELECT cart_id FROM orders").fetchone()[0] is None
        assert current.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            current.execute("UPDATE orders SET total_cents = -1")
    finally:
        current.close()


def test_revision_upgrade_preserves_orders_on_each_backend(database_location):
    upgrade(database_url(database_location), revision="0001")
    connection = connect(database_location)
    try:
        connection.execute("INSERT INTO products (name, description, category, price_cents, stock, illustration, initials) VALUES ('Original', 'Description', 'Home', 500, 3, 'mug', 'O')")
        connection.execute("INSERT INTO orders (reference, checkout_key, total_cents) VALUES ('MM-OLD', 'old-key', 500)")
        connection.execute("INSERT INTO order_items (order_id, product_id, product_name, unit_price_cents, quantity) VALUES (1, 1, 'Original', 500, 1)")
        connection.commit()
        upgrade(database_url(database_location))
        assert connection.execute("SELECT reference FROM orders").fetchone()[0] == "MM-OLD"
        assert connection.execute("SELECT quantity FROM order_items").fetchone()[0] == 1
        assert connection.execute("SELECT cart_id FROM orders").fetchone()[0] is None
    finally:
        connection.close()
