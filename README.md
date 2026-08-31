# Mini Market

A small Python e-commerce prototype exploring a practical question: **how do you accept an order without losing track of stock?** Browse six everyday products, edit a cart, and place a simulated order. Prices are in AUD; no money is charged and no goods are shipped.

Built with Flask, SQLite, Jinja templates, and CSS. No frontend build process, external assets, payment account, or API key is required. Product illustrations are CSS shapes.

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

The database is local at `instance/market.sqlite`, ignored by Git. Initialisation refuses to overwrite an existing database. To deliberately erase demo orders and restore starting stock:

```powershell
.\.venv\Scripts\python -m flask --app app init-db --reset
```

An ephemeral secret is generated for local use; restarting the server invalidates carts and forms. Set a persistent random `SECRET_KEY` environment variable for sessions to survive restarts. Never commit the key. Debug mode is off by default.

## Engineering principles

- **Customer focus:** visible prices and stock, labelled forms, keyboard focus, responsive pages, empty states, and actionable errors that preserve the cart.
- **Accountability and accuracy:** server-authoritative prices, integer cents, non-negative stock, and transaction rollback on failure.
- **Integrity:** explicitly simulated checkout, clear limitations, no claims of real payment processing or NAB endorsement.
- **Collaboration and learning:** separated responsibilities, documented trade-offs, reproducible tests, and a pull-request CI workflow support review and discussion. A solo prototype does not establish a history of teamwork.

These are design goals aligned with the supplied role description's emphasis on quality, problem solving, communication and learning, not a claim about an official interview scoring rubric.

## Architecture

```text
Browser forms → Flask routes → checkout service → SQLite
                    ↓                              ↓
              Jinja templates               products / orders /
                                            order_items
```

| File | Responsibility |
| --- | --- |
| `mini_market/__init__.py` | Configuration, CSRF, routes and customer errors |
| `mini_market/checkout.py` | Validation, transaction, duplicate-submission handling |
| `mini_market/db.py` | Connections and demo-data CLI |
| `mini_market/schema.sql` | Tables, foreign keys and constraints |
| `mini_market/templates/` | Catalogue, cart, receipt and error pages |
| `mini_market/static/style.css` | Responsive styling and product illustrations |
| `tests/` | Service, concurrency and HTTP tests |

The signed session cookie stores IDs and quantities, not prices. It is tamper-evident, not encrypted; no sensitive customer data is collected. Jinja escapes text, SQL uses bound parameters, and every mutation is a POST with a session-bound CSRF token.

### Checkout

1. Validate CSRF and the checkout key. Cart changes generate a new key.
2. Acquire a SQLite write reservation with `BEGIN IMMEDIATE` before reading stock.
3. If the key already created an order, return that order.
4. Validate quantities and availability; read prices from the database.
5. Save the order and item snapshots, then reduce stock.
6. Commit everything together, or roll everything back on failure.
7. Clear the cart and redirect to the receipt. A repeated POST with the same key resolves to the same order.

Stock is not reserved in the cart. Another customer may buy it first, so checkout checks again inside the transaction. SQLite serialises writers: a second checkout waits, then reads updated stock. A test exercises this using two connections in separate threads.

### HTTP interface

These are HTML form endpoints, not a JSON REST API.

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/` | Catalogue |
| GET | `/cart` | Cart review |
| POST | `/cart/<product_id>` | Add, update or remove |
| POST | `/checkout` | Idempotent simulated order |
| GET | `/orders/<reference>` | Receipt using an unguessable link |

Successful mutations use `303` redirects. Invalid forms use `400`, missing resources `404`, stock/stale-checkout conflicts `409`, and checkout database failures `503`. Detailed database errors go to logs, not the customer.

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
```

Tests use temporary databases. Coverage includes totals, historical price snapshots, invalid quantities, stock conflicts, a failure midway through an order, concurrent checkout for the last item, duplicate submissions, CSRF, and the complete HTTP journey. GitHub Actions runs the suite on pushes and pull requests once the workflow is pushed.

## Trade-offs and limits

- SQLite is simple and transactional; serialised writes limit throughput. A larger store should evaluate PostgreSQL under realistic load.
- Server-rendered pages reduce dependencies; cart changes reload the page.
- There are no real payments. A payment integration needs explicit order states, verified webhooks, idempotency and failure recovery.
- There are no accounts. Receipt URLs are bearer links; anyone with a link can view its non-personal receipt. Production orders need authentication and ownership checks.
- This is a local demo. Public hosting needs a production WSGI server, HTTPS, secure cookies, managed secrets, backups, monitoring and abuse controls.
- Concurrent browser tabs can submit stale cart state. Checkout keys reject outdated forms when the current session has changed, but full coordination needs server-side carts and version checks.
- Automated service/HTTP tests are not a full accessibility audit or production load test.

## Interview preparation and authorship

Read [the walkthrough](docs/INTERVIEW.md) and [design decisions](docs/DESIGN.md). This prototype was generated with AI assistance. Do not claim all code was written independently or that a planned failure test was an incident you personally encountered. Build an honest account of what you reviewed, ran, changed and can explain.

## Licence

MIT — see [LICENSE](LICENSE).
