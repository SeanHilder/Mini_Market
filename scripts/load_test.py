"""Isolated PostgreSQL application/DB load test (WSGI, not a network benchmark)."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from html.parser import HTMLParser
import json
import logging
import math
import os
from pathlib import Path
import secrets
import time
import uuid

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from mini_market import create_app
from mini_market.db import get_db, init_db


@contextmanager
def isolated_database(url):
    """Use a random schema; never reset or drop the caller's existing tables."""
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("Load testing requires a PostgreSQL URL in TEST_DATABASE_URL.")
    schema = "mm_load_" + uuid.uuid4().hex
    admin = psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1), autocommit=True)
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        target = make_url(url).update_query_dict({"options": "-csearch_path=" + schema})
        yield target.render_as_string(hide_password=False)
    finally:
        # Generated identifier, quoted as an SQL identifier. No caller-controlled DROP target.
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


class FormFields(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.fields = {}
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag == "input" and values.get("type") == "hidden":
            self.fields[values["name"]] = values.get("value", "")


def buyer(app, product_id):
    client = app.test_client()
    fields = FormFields(client.get("/").get_data(as_text=True)).fields
    added = client.post(f"/cart/{product_id}", data={**fields, "action": "add"})
    if added.status_code != 303:
        raise AssertionError("Load-test cart setup failed")
    checkout = FormFields(client.get("/cart").get_data(as_text=True)).fields
    return client, checkout


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def run_batch(buyers, workers):
    def submit(prepared):
        client, fields = prepared
        start = time.perf_counter()
        response = client.post("/checkout", data=fields)
        return response.status_code, (time.perf_counter() - start) * 1000, response.headers.get("Location")
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(submit, buyers))
    elapsed = time.perf_counter() - start
    statuses = {str(code): sum(result[0] == code for result in results) for code in sorted({result[0] for result in results})}
    latencies = [result[1] for result in results]
    return {
        "attempts": len(results), "workers": workers, "duration_seconds": round(elapsed, 3),
        "attempts_per_second": round(len(results) / elapsed, 2), "status_counts": statuses,
        "latency_ms": {"p50": round(percentile(latencies, .5), 2), "p95": round(percentile(latencies, .95), 2), "max": round(max(latencies), 2)},
    }, results


def run(url, requests=100, workers=8):
    if not 2 <= requests <= 10000 or not 1 <= workers <= 64:
        raise ValueError("Use 2..10000 requests and 1..64 workers.")
    with isolated_database(url) as database:
        app = create_app({"TESTING": True, "DATABASE": database, "SECRET_KEY": secrets.token_hex(32)})
        # Avoid benchmarking console output; counters and histograms remain active.
        app.logger.handlers = [logging.NullHandler()]
        with app.app_context():
            init_db()
            connection = get_db()
            connection.execute("UPDATE products SET stock = ? WHERE id = 1", (requests,))
            connection.commit()
            version = connection.execute("SHOW server_version").fetchone()["server_version"]

        # Catalogue/cart setup is outside the timed checkout batch.
        regular, _ = run_batch([buyer(app, 1) for _ in range(requests)], workers)
        oversell, _ = run_batch([buyer(app, 5) for _ in range(max(workers * 2, 2))], workers)

        original_client, fields = buyer(app, 2)
        cookie = original_client.get_cookie("session").value
        retries = []
        for _ in range(max(workers * 2, 2)):
            client = app.test_client()
            client.set_cookie("session", cookie)
            retries.append((client, dict(fields)))
        duplicate, duplicate_results = run_batch(retries, workers)

        with app.app_context():
            connection = get_db()
            stock = {row["id"]: row["stock"] for row in connection.execute("SELECT id, stock FROM products").fetchall()}
            counts = connection.execute("SELECT COUNT(*) AS count, SUM(total_cents) AS total FROM orders").fetchone()
            items = connection.execute("SELECT SUM(unit_price_cents * quantity) AS total FROM order_items").fetchone()
            cart_rows = connection.execute("SELECT COUNT(*) AS count FROM cart_items").fetchone()
        checks = {
            "regular_orders_succeeded": regular["status_counts"] == {"303": requests},
            "last_item_has_one_winner": oversell["status_counts"] == {"303": 1, "409": oversell["attempts"] - 1},
            "retries_return_one_receipt": duplicate["status_counts"] == {"303": duplicate["attempts"]} and len({result[2] for result in duplicate_results}) == 1,
            "stock_matches_orders": stock[1] == 0 and stock[5] == 0 and stock[2] == 17 and min(stock.values()) >= 0,
            "order_count_exact": counts["count"] == requests + 2,
            "totals_match_items": counts["total"] == items["total"] == requests * 2400 + 1600 + 1800,
            "failed_carts_preserved": cart_rows["count"] == oversell["attempts"] - 1,
        }
        return {
            "scope": "Local WSGI application plus PostgreSQL; excludes network/proxy/TLS, cart setup and console logging",
            "postgresql_version": version,
            "scenarios": {"regular_checkout": regular, "last_item_contention": oversell, "duplicate_checkout": duplicate},
            "invariants": checks,
            "passed": all(checks.values()),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, default=Path("instance/load-results.json"))
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        parser.error("Set TEST_DATABASE_URL to a PostgreSQL test database; credentials must not be command-line arguments.")
    try:
        result = run(url, args.requests, args.workers)
    except Exception as error:
        # Never print database exception text: it can include credentials/SQL values.
        print(json.dumps({"passed": False, "error_type": type(error).__name__}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
