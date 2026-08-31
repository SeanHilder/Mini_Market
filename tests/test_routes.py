import pytest

def test_catalogue_and_empty_cart(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Everyday tote" in response.data
    assert b"Sold out" in response.data
    assert b"Your cart is empty" in client.get("/cart").data

def test_complete_journey_and_repeat_submit(client, form, database):
    assert client.post("/cart/1", data={**form, "action": "add"}).status_code == 303
    assert client.post("/cart/1", data={**form, "action": "update", "quantity": "2"}).status_code == 303
    with client.session_transaction() as session:
        key = session["checkout_key"]
    payload = {**form, "checkout_key": key, "price_cents": "1", "total_cents": "1"}
    response = client.post("/checkout", data=payload)
    assert response.status_code == 303
    receipt = client.get(response.location)
    assert b"$48.00" in receipt.data
    assert b"Good things, confirmed" in receipt.data
    assert client.post("/checkout", data=payload).location == response.location
    assert database.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
    assert b"Your cart is empty" in client.get("/cart").data

@pytest.mark.parametrize("quantity", ["0", "-1", "100", "1.5", "hello", ""])
def test_quantity_validation(client, form, quantity):
    assert client.post("/cart/1", data={**form, "action": "update", "quantity": quantity}).status_code == 400

def test_remove(client, form):
    client.post("/cart/1", data={**form, "action": "add"})
    client.post("/cart/1", data={**form, "action": "remove"})
    assert b"Your cart is empty" in client.get("/cart").data

def test_stock_changes_before_checkout(client, form, database):
    client.post("/cart/5", data={**form, "action": "add"})
    database.execute("UPDATE products SET stock = 0 WHERE id = 5")
    database.commit()
    with client.session_transaction() as session:
        key = session["checkout_key"]
    response = client.post("/checkout", data={**form, "checkout_key": key})
    assert response.status_code == 409
    assert b"Only 0 of Desk planter available" in response.data
    with client.session_transaction() as session:
        assert session["cart"] == {"5": 1}

def test_csrf_and_unknown_resources(client, form):
    assert client.post("/cart/1", data={"action": "add"}).status_code == 400
    assert client.post("/checkout", data={"csrf_token": "wrong"}).status_code == 400
    assert client.post("/cart/999", data={**form, "action": "add"}).status_code == 404
    assert client.get("/orders/unknown").status_code == 404
    assert client.get("/missing").status_code == 404
    assert client.get("/checkout").status_code == 405

def test_stale_checkout_and_sold_out(client, form):
    with client.session_transaction() as session:
        old_key = session["checkout_key"]
    client.post("/cart/1", data={**form, "action": "add"})
    assert client.post("/checkout", data={**form, "checkout_key": old_key}).status_code == 409
    assert client.post("/cart/6", data={**form, "action": "add"}).status_code == 409

def test_database_error_is_safe(client, form, database):
    client.post("/cart/1", data={**form, "action": "add"})
    database.execute("CREATE TRIGGER fail_order BEFORE INSERT ON orders BEGIN SELECT RAISE(ABORT, 'private detail'); END")
    database.commit()
    with client.session_transaction() as session:
        key = session["checkout_key"]
    response = client.post("/checkout", data={**form, "checkout_key": key})
    assert response.status_code == 503
    assert b"No payment was taken" in response.data
    assert b"private detail" not in response.data

def test_security_headers(client):
    response = client.get("/")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]

def test_malformed_tokens_and_very_large_quantity(client, form):
    assert client.post("/cart/1", data={"csrf_token": "é", "action": "add"}).status_code == 400
    assert client.post("/checkout", data={**form, "checkout_key": "é"}).status_code == 409
    assert client.post("/cart/1", data={**form, "action": "update", "quantity": "9" * 5000}).status_code == 400
