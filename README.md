# Mini Market

A small Python e-commerce prototype exploring a practical question: **how do you accept an order without losing track of stock?** Browse six everyday products, edit a cart, and place a simulated order. Prices are in AUD; no money is charged and no goods are shipped.

Built with Flask, SQLite or PostgreSQL, Jinja templates, and CSS. Includes server-side carts, optimistic version checks, JSON telemetry, Prometheus metrics and Alembic migrations. No frontend build process, payment account or API key is required for the local demo. Product illustrations are CSS shapes.

## Run locally

Use Python 3.11 or newer (tested locally on 3.13). In PowerShell:

```powershell
git clone https://github.com/SeanHilder/Mini_Market.git
cd Mini_Market
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m flask --app app init-db
.\.venv\Scripts\python -m flask --app app run
```

Open http://127.0.0.1:5000. Calling the environment's Python directly avoids PowerShell activation-policy issues. On macOS/Linux, replace `.\.venv\Scripts\python` with `.venv/bin/python`.

The default database is local at `instance/market.sqlite`, ignored by Git. For an existing checkout, install the updated dependencies and run `python -m flask --app app migrate-db` to preserve products/orders. Do not use reset to upgrade. See [the operations guide](docs/OPERATIONS.md) for PostgreSQL, migration and monitoring setup. To deliberately erase demo orders/carts and restore starting stock:

```powershell
.\.venv\Scripts\python -m flask --app app init-db --reset
```

An ephemeral secret is generated for local use; restarting invalidates access to existing anonymous carts/forms. Set a persistent random `SECRET_KEY` environment variable for sessions to survive restarts. Never commit the key. Debug mode is off by default. Legacy cookie-only carts are cleared on upgrade; historical orders remain intact.

## Engineering principles

- **Customer focus:** visible prices and stock, labelled forms, keyboard focus, responsive pages, empty states, and actionable errors that preserve the cart.
- **Accountability and accuracy:** server-authoritative prices, integer cents, non-negative stock, and transaction rollback on failure.
- **Integrity:** explicitly simulated checkout, clear limitations, no claims of real payment processing or NAB endorsement.
- **Collaboration and learning:** separated responsibilities, documented trade-offs, reproducible tests, and a pull-request CI workflow support review and discussion. A solo prototype does not establish a history of teamwork.

These are design goals aligned with the supplied role description's emphasis on quality, problem solving, communication and learning, not a claim about an official interview scoring rubric.

## Architecture

```text
Browser forms → Flask routes → cart / checkout services → SQLite or PostgreSQL
                    ↓                              ↓
              Jinja templates               products / orders /
                                            order_items
```

| File | Responsibility |
| --- | --- |
| `mini_market/__init__.py` | Configuration, CSRF, routes and customer errors |
| `mini_market/checkout.py` | Validation, transaction, duplicate-submission handling |
| `mini_market/db.py` | Connections and demo-data CLI |
| `mini_market/carts.py` | Persistent carts, version validation and mutation transactions |
| `migrations/versions/` | Versioned schema, foreign keys and constraints |
| `mini_market/observability.py` | Safe JSON logs, protected metrics and request IDs |
| `mini_market/templates/` | Catalogue, cart, receipt and error pages |
| `mini_market/static/style.css` | Responsive styling and product illustrations |
| `tests/` | Service, concurrency and HTTP tests |

The signed cookie holds an opaque cart ID and CSRF token; quantities and checkout keys live in the database. It is tamper-evident, not encrypted; no sensitive customer data is collected. Jinja escapes text, SQL uses bound parameters, and every mutation is a POST with a session-bound CSRF token and cart version.

### Checkout

1. Validate CSRF and the submitted cart version/key.
2. Lock the cart row on PostgreSQL, or acquire SQLite's write reservation.
3. If this key already created an order for this cart, return it without modifying any newer cart contents.
4. Reject stale versions; lock products in ascending ID order on PostgreSQL, validate stock, and read authoritative prices.
5. Save the order and item snapshots, then reduce stock.
6. Commit everything together, or roll everything back on failure.
7. Clear the cart and increment its version inside the same transaction, then redirect to the receipt.

Stock is not reserved in the cart. Another customer may buy it first, so checkout checks again inside the transaction. Stale tab submissions receive `409` with current cart contents. Threaded tests exercise contested stock, simultaneous edits and checkout retries on both databases.

### HTTP interface

These are HTML form endpoints, not a JSON REST API.

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/` | Catalogue |
| GET | `/cart` | Cart review |
| POST | `/cart/<product_id>` | Add, update or remove |
| POST | `/checkout` | Idempotent simulated order |
| GET | `/orders/<reference>` | Receipt using an unguessable link |
| GET | `/healthz`, `/readyz` | Process liveness and migrated-database readiness |
| GET | `/metrics` | Prometheus output; disabled unless a bearer token is configured |

Successful mutations use `303` redirects. Invalid forms use `400`, missing resources `404`, stock/version conflicts `409`, and database failures `503`. JSON logs contain safe generated request IDs, internal order IDs and exception classes; raw paths, receipt links, SQL parameters, tokens and credentials are excluded.

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
```

Tests use temporary SQLite databases and, when `TEST_DATABASE_URL` is set, isolated PostgreSQL schemas. Coverage includes transactional failures, concurrent cart updates, last-item contention, retry safety, migrations and telemetry privacy. PostgreSQL cases explicitly skip when no test URL is supplied. GitHub Actions provisions PostgreSQL 17 and runs both suites plus a load smoke test.

Run `python -m scripts.load_test --requests 100 --workers 8` with `TEST_DATABASE_URL` set for an isolated PostgreSQL application/DB workload. Its JSON report includes throughput, latency percentiles and correctness invariants. It excludes network/proxy/TLS and is not a production capacity claim. See [operations and load testing](docs/OPERATIONS.md).

## Trade-offs and limits

- SQLite serialises writes; PostgreSQL locks relevant rows. Connections currently open per request; production pooling and externally driven HTTP capacity tests remain future work.
- Server-rendered pages reduce dependencies; cart changes reload the page.
- There are no real payments. A payment integration needs explicit order states, verified webhooks, idempotency and failure recovery.
- There are no accounts. Receipt URLs are bearer links; anyone with a link can view its non-personal receipt. Production orders need authentication and ownership checks.
- This is a local demo. Public hosting needs a production WSGI server, HTTPS, secure cookies, managed secrets, backups, monitoring and abuse controls.
- Server-side versions prevent lost cart updates, but tabs do not automatically refresh. Anonymous carts need expiry/cleanup and account recovery for production use.
- Metrics are per process and reset on restart; multiple workers require an aggregation strategy. Proxy/WSGI access logs must also redact receipt bearer paths.
- Automated service/HTTP tests are not a full accessibility audit or production load test.

## Interview preparation and authorship

Read [the walkthrough](docs/INTERVIEW.md) and [design decisions](docs/DESIGN.md). This prototype was generated with AI assistance. Do not claim all code was written independently or that a planned failure test was an incident you personally encountered. Build an honest account of what you reviewed, ran, changed and can explain.

## Licence

MIT — see [LICENSE](LICENSE).
