import io
import json
import logging

from mini_market.observability import JsonFormatter


def test_metrics_require_token_and_have_bounded_labels(app, client, form):
    assert client.get("/metrics").status_code == 404
    app.config["METRICS_TOKEN"] = "test-metrics-token"
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    client.get("/orders/private-bearer-reference?token=private-query")
    client.post("/cart/1", data={**form(), "action": "add"})
    payload = form()
    client.post("/checkout", data=payload)
    client.post("/checkout", data=payload)
    result = client.get("/metrics", headers={"Authorization": "Bearer test-metrics-token"})
    assert result.status_code == 200
    assert b'mini_market_checkouts_total{outcome="created"} 1.0' in result.data
    assert b'mini_market_checkouts_total{outcome="replayed"} 1.0' in result.data
    assert b'/orders/<reference>' in result.data
    for private in (b"private-bearer-reference", b"private-query", b"test-metrics-token", payload["checkout_key"].encode()):
        assert private not in result.data


def test_json_logs_redact_bearers_and_generate_request_ids(app, client, form):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    app.logger.addHandler(handler)
    try:
        response = client.get("/orders/secret-receipt?token=secret-query", headers={"X-Request-ID": "untrusted-request-id", "Authorization": "Bearer secret-auth"})
        client.post("/cart/1", data={**form(), "action": "add"})
        payload = form()
        client.post("/checkout", data=payload)
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        assert response.headers["X-Request-ID"] != "untrusted-request-id"
        checkout = next(record for record in records if record["event"] == "checkout")
        assert isinstance(checkout["order_id"], int)
        assert checkout["outcome"] == "created"
        for secret in ("secret-receipt", "secret-query", "secret-auth", "untrusted-request-id", payload["csrf_token"], payload["checkout_key"], "MM-"):
            assert secret not in stream.getvalue()
    finally:
        app.logger.removeHandler(handler)


def test_health_does_not_create_cart_and_readiness_checks_schema(client, database):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert database.execute("SELECT COUNT(*) FROM carts").fetchone()[0] == 0
    assert "Set-Cookie" not in client.get("/metrics").headers


def test_unexpected_error_is_safe_and_counted(app, client):
    app.config["TESTING"] = False
    def broken():
        raise RuntimeError("secret-database-url")
    app.add_url_rule("/test-failure", view_func=broken)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    app.logger.addHandler(handler)
    try:
        response = client.get("/test-failure")
        assert response.status_code == 500
        assert "X-Request-ID" in response.headers
        assert "secret-database-url" not in stream.getvalue()
        assert b"secret-database-url" not in response.data
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        error = next(record for record in records if record.get("event") == "internal_error")
        assert error["error_type"] == "RuntimeError"
    finally:
        app.logger.removeHandler(handler)
