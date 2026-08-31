# Design decisions

## Python and Flask

Python is the author's strongest stated language. Flask exposes routing, validation, templates and SQL without a separate frontend. Django's built-in account/admin features could help a larger shop, but are outside this scope. Rust or Go would increase the learning burden before the interview.

## Separate business rules from HTTP

`place_order(connection, cart, checkout_key)` works without Flask request/session objects. Routes handle browser concerns; the service handles order consistency. Tests can run identical rules through separate database connections. Functions keep the design small; a custom `CheckoutError` identifies customer-correctable problems without an unnecessary inheritance hierarchy.

## Relational model

One order has many order items; each item references a product. Item names and unit prices are snapshots so catalogue changes do not rewrite receipts. Foreign keys prevent dangling references; checks protect quantities and stock.

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

Checking stock outside a transaction lets two buyers both observe the last item. `BEGIN IMMEDIATE` reserves SQLite's writer before stock is read. After the first commits, the next checks fresh data. The trade-off is serialising even unrelated purchases. Keep the transaction short and never call a payment API while holding the lock.

The rollback test injects a SQLite trigger that fails the second item insertion. It proves the first stock update and order header are undone, rather than only testing pre-write validation.

## Duplicate submission

POST/redirect/GET reduces refresh resubmissions but does not solve double clicks. A random checkout key, constrained UNIQUE in the database, identifies an attempt. The service checks it inside the transaction; retries return the saved receipt. Cart changes rotate the key. This is scoped to a signed session, not a general payment idempotency protocol.

## Validation boundaries

HTML inputs guide customers; server validation enforces rules; database constraints provide a final safeguard. Form prices are ignored. CSRF tokens defend against cross-site form submission; signed cookies defend session integrity. Neither replaces authentication.

## Complexity

The cart dictionary maps product IDs to quantities: average O(1) lookup/update, O(n) space for n distinct products. Checkout iterates over n items with indexed database queries. Strictly calling the whole operation O(n) ignores database lookup costs, locks and disk work. Batch fetching would reduce query round trips for larger carts; six demo products do not justify a complicated data layer.

## Next improvements

1. Server-side carts and version checks for simultaneous tab updates.
2. Structured logs and operational metrics with safe request/order identifiers.
3. Payment sandbox, explicit order states and verified callbacks.
4. PostgreSQL load testing and schema migrations.
5. Browser accessibility testing with keyboard and screen reader.

Select improvements for an actual need. Caching, microservices and cloud hosting are not automatically the best next step.
