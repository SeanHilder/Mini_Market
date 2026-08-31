# Database, cart concurrency and operations

## Upgrade an existing checkout

Stop the old application process and back up `instance/market.sqlite` before upgrading. Install dependencies, migrate, then start the server:

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m flask --app app migrate-db
.\.venv\Scripts\python -m flask --app app run
```

`migrate-db` is repeatable and does not seed, reset stock or delete orders. Revision `0001` is the original product/order schema; `0002` adds carts and an optional order-to-cart relationship. The recognised original SQLite schema is stamped at `0001` and upgraded in place. Old receipts remain accessible. Unrecognised legacy table/column layouts are rejected for manual review.

Browser carts from the original cookie-only version are cleared on upgrade. Persisted products and orders are preserved. Anonymous cart contents are now in the database; the signed cookie carries an opaque cart ID and CSRF token. Configure a stable random `SECRET_KEY` to keep existing browser sessions usable across restarts. Losing or clearing that cookie also loses access to the anonymous cart.

Use `init-db` only to initialise an empty database with demo products. `init-db --reset` explicitly erases demo orders/carts and resets stock. It is not a migration command. The PostgreSQL user needs DDL privileges for migrations; use a separate migration role when deploying with a restricted runtime role. Run migrations once during deployment, never concurrently from each application worker.

## PostgreSQL locally

The default remains SQLite. With Docker running:

```powershell
$env:POSTGRES_PASSWORD = [guid]::NewGuid().ToString('N')
docker compose up -d --wait postgres
$env:DATABASE_URL = "postgresql+psycopg://mini_market:$($env:POSTGRES_PASSWORD)@127.0.0.1:55432/mini_market"
$env:SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
.\.venv\Scripts\python -m flask --app app init-db
.\.venv\Scripts\python -m flask --app app run
```

The Compose service binds to localhost and uses a named volume. Keep the generated password and secret in your local secret store; do not commit them or generate a new database password each time you reuse an existing volume. `docker compose stop` stops the service while retaining data. Avoid `down --volumes` unless intentionally deleting that database.

The application uses psycopg for PostgreSQL and the Python SQLite driver locally. A small adapter normalises parameter binding and named rows. SQLAlchemy is used by Alembic for dialect-aware schema migration, not as an ORM. PostgreSQL connections have a 5-second connection timeout, 10-second lock timeout and 15-second statement timeout. This prototype opens one connection per request; production connection pooling remains future work.

## How competing tabs are handled

1. Every cart has a database `version`, initially zero.
2. Each form includes the version it displayed.
3. A mutation locks the cart row (`FOR UPDATE` on PostgreSQL; a SQLite write transaction locally).
4. A version mismatch returns `409` with current cart contents; no mutation is made.
5. A successful mutation increments the version and rotates the checkout key.
6. Checkout locks the cart, validates its version/key, locks products in ascending ID order, and creates the order, reduces stock, empties the cart and increments its version in one transaction.
7. A retry of a completed checkout returns the original receipt only when that order belongs to the same cart. It never clears items added after that order.

The first visit establishes the anonymous cookie. Simultaneous first-ever requests without that cookie can create separate anonymous carts. Once the cookie exists, tabs share database state. There is no automatic cross-tab refresh: users get an explicit conflict on stale submission. Carts are not stock reservations. Cart expiry/cleanup and account-based recovery are not implemented.

## JSON logs

Each application HTTP request gets a server-generated `X-Request-ID`. Client-supplied request IDs are ignored. Logs contain an allowlist of timestamp, level, event, request ID, route **template**, method, status and duration. Checkout events add outcome and the internal numeric order ID. Database failures record the exception class, not its message or parameters.

```json
{"timestamp":"2026-09-14T00:00:00+00:00","level":"INFO","event":"checkout","request_id":"example-generated-id","order_id":12,"outcome":"created"}
```

The order ID is an internal diagnostic identifier, not the random receipt URL. Cookies, cart IDs, CSRF tokens, checkout keys, authorization headers, query strings, raw paths and database URLs are excluded. Werkzeug access logs are disabled because they include receipt bearer paths. Configure reverse-proxy and production WSGI access logs to redact those paths too. SQL debugging/echo is not enabled. Logging does not persist to a file automatically; collect stderr with your hosting platform.

## Metrics and probes

Set `METRICS_TOKEN` to enable `/metrics`. It is disabled (`404`) otherwise. Scraping requires `Authorization: Bearer <token>`; missing or wrong credentials receive `401`. Use HTTPS outside localhost and restrict the endpoint to your monitoring network.

```powershell
$env:METRICS_TOKEN = [guid]::NewGuid().ToString('N')
# Start/restart the application with this environment, then:
Invoke-WebRequest http://127.0.0.1:5000/metrics -Headers @{Authorization="Bearer $env:METRICS_TOKEN"}
```

| Metric | Labels / purpose |
| --- | --- |
| `mini_market_http_requests_total` | method, route template, status |
| `mini_market_http_duration_seconds` | latency histogram by method and route template |
| `mini_market_checkouts_total` | `created`, `replayed`, `conflict`, `error` |
| `mini_market_cart_conflicts_total` | rejected stock/version conflicts during cart changes |

Labels deliberately exclude request/order IDs and arbitrary URLs to avoid unbounded cardinality. Metrics requests do not count themselves. Database/CSRF failures before a valid checkout attempt are still captured in HTTP request metrics; checkout counters represent requests reaching the checkout outcome logic (plus checkout database failures).

Metrics are in-memory and **per process**. They reset on restart. This implementation is suitable for the single-process demo: do not treat separate workers' registries as an aggregate. Before multi-worker deployment, configure Prometheus multiprocess collection or an external metrics backend.

`/healthz` checks process liveness without database access. `/readyz` verifies database connectivity and revision `0002`, returning `503` when unavailable/outdated. Probes, static files and scrapes do not create carts.

## PostgreSQL tests and load test

```powershell
$env:TEST_DATABASE_URL = $env:DATABASE_URL
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m scripts.load_test --requests 100 --workers 8
```

The PostgreSQL tests and runner create random `mm_test_*` / `mm_load_*` schemas and remove **only their own schema** afterward. Existing application data is untouched. Use a dedicated test database and a role allowed to create schemas. Interrupted runs may leave one of these schemas behind for inspection. The connection URL is read from the environment and omitted from reports/logs.

Without `TEST_DATABASE_URL`, pytest runs SQLite tests and explicitly skips PostgreSQL cases. With it set, the suite runs on both databases. Tests cover a real mid-transaction database failure, contested stock, simultaneous tab mutations, checkout-versus-edit races, concurrent duplicate submissions, migration preservation and telemetry privacy.

The load test submits checkout through Flask's WSGI test client and a real PostgreSQL database. It measures **application/database work, not a deployed HTTP service**: network, proxy/TLS, catalogue/cart setup and console log output are excluded. Each simulated buyer has its own client/session; duplicate submissions deliberately reuse an established session cookie. Cart preparation happens before timed checkout batches.

Scenarios: ordinary checkout; many carts competing for the last item; repeated simultaneous submissions of one checkout. The JSON report includes attempt throughput, p50/p95/max latency, status counts and correctness invariants. Failures produce a nonzero exit code. Rates are observations of that machine/run, not capacity guarantees; there are no arbitrary latency pass thresholds.

GitHub Actions provisions PostgreSQL 17, runs both database suites and a 40-request load smoke test, and uploads its report. For useful capacity planning, follow this with an external HTTP workload against the intended production server and connection pool.

References: [Alembic connection sharing](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands), [PostgreSQL row locking](https://www.postgresql.org/docs/current/explicit-locking.html), [Prometheus multiprocess limitations](https://prometheus.github.io/client_python/multiprocess/).
