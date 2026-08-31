import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from mini_market.checkout import CheckoutError, place_order
from mini_market.db import connect

def test_prices_and_historical_snapshot(database):
    reference = place_order(database, {"1": 2, "2": 1}, "first")
    order = database.execute("SELECT * FROM orders WHERE reference = ?", (reference,)).fetchone()
    assert order["total_cents"] == 6600
    assert database.execute("SELECT stock FROM products WHERE id = 1").fetchone()[0] == 10
    database.execute("UPDATE products SET price_cents = 9999, name = 'Changed' WHERE id = 1")
    database.commit()
    item = database.execute("SELECT * FROM order_items WHERE product_id = 1").fetchone()
    assert item["unit_price_cents"] == 2400
    assert item["product_name"] == "Everyday tote"

@pytest.mark.parametrize("quantity", [0, -1, 100, 1.5, "2", True])
def test_invalid_quantity(database, quantity):
    with pytest.raises(CheckoutError):
        place_order(database, {"1": quantity}, "bad")
    assert database.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    assert database.execute("SELECT stock FROM products WHERE id = 1").fetchone()[0] == 12

@pytest.mark.parametrize("cart", [{}, {"999": 1}, {"1": 1, "5": 2}, {"6": 1}])
def test_unavailable_or_empty_order(database, cart):
    with pytest.raises(CheckoutError):
        place_order(database, cart, "unavailable")
    assert database.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    assert database.execute("SELECT stock FROM products WHERE id = 1").fetchone()[0] == 12

def test_failure_after_first_item_rolls_back_everything(database):
    database.execute("""CREATE TRIGGER fail_second_item BEFORE INSERT ON order_items
        WHEN NEW.product_id = 2 BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END""")
    database.commit()
    with pytest.raises(sqlite3.IntegrityError):
        place_order(database, {"1": 1, "2": 1}, "rollback")
    assert database.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    assert database.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 0
    assert database.execute("SELECT stock FROM products WHERE id = 1").fetchone()[0] == 12

def test_duplicate_checkout(database):
    first = place_order(database, {"5": 1}, "same-key")
    assert place_order(database, {}, "same-key") == first
    assert database.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
    assert database.execute("SELECT stock FROM products WHERE id = 5").fetchone()[0] == 0

def test_two_customers_cannot_buy_last_item(app):
    barrier = Barrier(2)
    def purchase(key):
        connection = connect(app.config["DATABASE"])
        try:
            barrier.wait(timeout=5)
            try:
                return place_order(connection, {"5": 1}, key)
            except CheckoutError:
                return "out-of-stock"
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(purchase, ["customer-a", "customer-b"]))
    assert results.count("out-of-stock") == 1
    connection = connect(app.config["DATABASE"])
    try:
        assert connection.execute("SELECT stock FROM products WHERE id = 5").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
    finally:
        connection.close()
