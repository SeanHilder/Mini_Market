# Design decisions

## Python and Flask

Python is the author's strongest stated language. Flask exposes routing, validation, templates and SQL without a separate frontend. Django's built-in account/admin features could help a larger shop, but are outside this scope. Rust or Go would increase the learning burden before the interview.

## Separate business rules from HTTP

`checkout_cart(connection, cart_id, version, checkout_key)` works without Flask request/session objects. Routes handle browser concerns; cart and checkout services handle consistency. Tests run the same rules through separate database connections. `place_order` remains a low-level entry point for tests/tools without a browser cart. A small immutable `OrderResult` distinguishes a newly created order from a retry.

## Relational model

One order has many order items; each item references a product. Item names and unit prices are snapshots so catalogue changes do not rewrite receipts. Carts have version numbers and child items; new orders reference their cart to scope retries. Foreign keys prevent dangling references; checks protect quantities and stock. Alembic revisions define and evolve this schema.

```sql
SELECT o.reference, i.product_name, i.quantity, i.unit_price_cents
FROM orders AS o
JOIN order_items AS i ON i.order_id = o.id
WHERE o.reference = ?;
```

The application uses two simple queries for receipts; this join illustrates the relationship. A unique order-reference index supports lookup. Future indexing should follow actual query plans and usage.

## Integer money

The fixed AUD catalogue stores 2400 for $24.00, avoiding binary floating-point rounding in totals. Tax, discounts and currency conversion would still need explicit rounding rules.

## Transaction boundary

Checking stock outside a transaction lets two buyers both observe the last item. SQLite uses `BEGIN IMMEDIATE`; PostgreSQL locks the cart and then product rows with `FOR UPDATE`. Product IDs are sorted to give overlapping orders a consistent lock order. The transaction includes clearing the cart, so checkout cannot erase an edit that succeeded afterward. Keep transactions short and never call payment APIs while holding locks.

The rollback test injects a database trigger that fails the second item insertion, on both SQLite and PostgreSQL. It proves the first stock update and order header are undone, rather than only testing pre-write validation.

## Duplicate submission

POST/redirect/GET reduces refresh resubmissions but does not solve double clicks. A random checkout key identifies an attempt. Under the cart lock, retries return a saved receipt only for the same cart; new attempts validate the displayed version. Mutations rotate the key and increment the version. A completed retry preserves newly added cart contents. This is a cart protocol, not a payment-provider integration.

## Validation boundaries

HTML inputs guide customers; server validation enforces rules; database constraints provide a final safeguard. Form prices are ignored. CSRF tokens defend against cross-site form submission; signed cookies defend session integrity. Neither replaces authentication.

## Complexity

The authoritative cart lives in indexed database rows; a request loads it into a product-ID-to-quantity dictionary with average O(1) lookup and O(n) memory. Checkout sorts n product IDs (O(n log n)) before indexed row-locking queries. Total cost also includes database indexes, locks, connection setup and disk work. Batch fetching and pooling are possible improvements, to be measured rather than assumed.

## Operational evidence

JSON telemetry uses generated request IDs, route templates and internal order IDs; receipt links and tokens are not logged. Prometheus counters/histograms have bounded labels and a protected scrape endpoint. Metrics are per process. Migrations preserve existing orders, and isolated PostgreSQL workload scenarios test correctness alongside throughput. See [the operations guide](OPERATIONS.md) for scope and limitations.

## Next improvements

1. Payment sandbox, explicit order states and verified callbacks.
2. Cart expiry, authentication and account-based recovery.
3. Connection pooling and external HTTP load tests against a production server.
4. Aggregated metrics for multi-worker deployment.
5. Browser accessibility testing with keyboard and screen reader.

Select improvements for an actual need. Caching, microservices and cloud hosting are not automatically the best next step.
