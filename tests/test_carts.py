from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from mini_market.carts import CartConflict, create_cart, get_cart, mutate_cart, read_cart
from mini_market.checkout import checkout_cart
from mini_market.db import connect


def test_stale_tab_does_not_overwrite(client, form, database):
    tab_a = form()
    tab_b = dict(tab_a)
    assert client.post("/cart/1", data={**tab_a, "action": "add"}).status_code == 303
    response = client.post("/cart/2", data={**tab_b, "action": "add"})
    assert response.status_code == 409
    assert b"another tab" in response.data
    with client.session_transaction() as session:
        assert "cart" not in session
        assert "checkout_key" not in session
        assert read_cart(database, session["cart_id"]) == {"1": 1}
    assert client.post("/cart/2", data={**form(), "action": "add"}).status_code == 303


def test_stale_checkout_and_replay_preserve_new_cart(client, form, database):
    client.post("/cart/1", data={**form(), "action": "add"})
    stale_checkout = form()
    client.post("/cart/2", data={**form(), "action": "add"})
    assert client.post("/checkout", data=stale_checkout).status_code == 409
    successful = form()
    original = client.post("/checkout", data=successful)
    assert original.status_code == 303
    client.post("/cart/3", data={**form(), "action": "add"})
    assert client.post("/checkout", data=successful).location == original.location
    with client.session_transaction() as session:
        assert read_cart(database, session["cart_id"]) == {"3": 1}


def test_missing_cart_version_fails_closed(client, form):
    payload = form()
    payload.pop("cart_version")
    assert client.post("/cart/1", data={**payload, "action": "add"}).status_code == 400


def test_concurrent_mutations_one_winner(app, database):
    cart_id = create_cart(database)
    barrier = Barrier(2)
    def update(product_id):
        connection = connect(app.config["DATABASE"])
        try:
            barrier.wait(timeout=5)
            try:
                mutate_cart(connection, cart_id, 0, product_id, "add")
                return "updated"
            except CartConflict:
                return "conflict"
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, [1, 2]))
    assert sorted(results) == ["conflict", "updated"]
    assert get_cart(database, cart_id)["version"] == 1
    assert len(read_cart(database, cart_id)) == 1


def test_concurrent_checkout_and_mutation_never_lose_new_items(app, database):
    cart_id = create_cart(database)
    mutate_cart(database, cart_id, 0, 1, "add")
    cart = get_cart(database, cart_id)
    barrier = Barrier(2)
    def operation(kind):
        connection = connect(app.config["DATABASE"])
        try:
            barrier.wait(timeout=5)
            try:
                if kind == "checkout":
                    checkout_cart(connection, cart_id, cart["version"], cart["checkout_key"])
                else:
                    mutate_cart(connection, cart_id, cart["version"], 2, "add")
                return kind
            except CartConflict:
                return "conflict"
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(operation, ["checkout", "update"]))
    assert results.count("conflict") == 1
    if "checkout" in results:
        assert read_cart(database, cart_id) == {}
        assert database.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
    else:
        assert read_cart(database, cart_id) == {"1": 1, "2": 1}
        assert database.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_simultaneous_retry_creates_one_order(app, database):
    cart_id = create_cart(database)
    mutate_cart(database, cart_id, 0, 5, "add")
    cart = get_cart(database, cart_id)
    barrier = Barrier(2)
    def checkout(_):
        connection = connect(app.config["DATABASE"])
        try:
            barrier.wait(timeout=5)
            return checkout_cart(connection, cart_id, cart["version"], cart["checkout_key"])
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(checkout, range(2)))
    assert results[0].reference == results[1].reference
    assert sum(result.replayed for result in results) == 1
    assert database.execute("SELECT stock FROM products WHERE id = 5").fetchone()[0] == 0
    assert get_cart(database, cart_id)["version"] == 2
