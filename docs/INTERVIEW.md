# Understanding and presenting Mini Market

## Accurate ownership

This is a recent AI-assisted prototype. Read the code, run the tests, and make a small change you can explain. Separate your idea and motivation from generated implementation and subsequent work. Do not describe a simulated failure test as a production incident or invent users, teammates, revenue or business results.

The role description emphasises problem solving, quality, testing/debugging, communication, accountability, learning and comfort with AI. This guide is preparation advice, not a verified interview rubric.

## Five-minute walkthrough

1. **Context (30 seconds):** A small store with simulated orders. Explain your e-commerce interest and, if accurate, how warehouse experience made stock accuracy meaningful to you.
2. **Architecture (45 seconds):** Browser → Flask routes → versioned cart/checkout services → SQLite or PostgreSQL. Why Python and why no separate frontend?
3. **Contribution (45 seconds):** What you specified, what AI generated, and what you reviewed or changed. Point to evidence of your learning.
4. **Technical focus (90 seconds):** Authoritative prices, integer cents, transactional stock checks, rollback and repeated submissions. Describe the concurrency test as a designed test of a known risk.
5. **Evidence and reflection (60 seconds):** Show tests and a customer error. Acknowledge absent payments/accounts; choose an improvement for a clear reason.

## Two-minute demo

1. Initialise fresh demo data before the interview, not during the walkthrough.
2. Show the sold-out cap and last remaining planter.
3. Add a tote, change quantity to two, and explain the $48.00 total.
4. Place a demo order; show receipt and updated stock.
5. For a live stock conflict, use two separate browser sessions. Put the planter in both carts, purchase in one, then submit the other. The second retains its cart and shows a stock error.

## Reading order

1. `migrations/versions/`: explain products, orders, order items, carts and cart items.
2. `checkout.py`: explain every query and the transaction boundary.
3. `__init__.py`: trace add-to-cart, checkout and confirmation.
4. `test_checkout.py`: understand failure injection and separate connections.
5. Templates: find where CSRF and checkout keys enter forms.

## Practise aloud

| Question | Points to understand |
| --- | --- |
| Why Python? | Your actual proficiency, readability and iteration speed. |
| Why a dictionary? | Request-local view of database cart rows; product ID to quantity, average constant-time lookup. |
| Why not trust the total? | Browser requests can be edited; database prices are authoritative. |
| What if stock sells out after adding? | No cart reservation; fresh check inside the checkout transaction. |
| What if a write fails? | Everything rolls back; show the failure test. |
| What about double clicks? | A checkout key returns the same order; redirect alone is insufficient. |
| What if two tabs edit? | Version checks under a cart lock let one change succeed; stale changes get 409 rather than overwriting it. |
| How do you investigate errors safely? | Generated request IDs and numeric order IDs; no bearer receipt links, cookies or credentials in logs. |
| How do schema changes preserve data? | Ordered Alembic migrations, legacy adoption and preservation tests, with a backup before upgrade. |
| What does the load test prove? | Correctness under measured application/DB concurrency on that environment, not production HTTP capacity. |
| Why snapshot prices? | Historical receipts survive catalogue changes. |
| Where is OOP? | Framework objects and custom exception; do not force inheritance into simple logic. Practise OOP concepts separately. |
| Is this REST? | HTML form application, not a JSON API; explain HTTP semantics accurately. |
| Production changes? | Authentication, payments lifecycle, secure hosting, operational visibility, backups and load testing. |
| AI contribution? | Actual assistance, verification, gaps and a decision/correction you can defend. |

## Behavioural preparation

Use real employment, university or basketball experiences for teamwork, conflict and accountability. This solo prototype demonstrates learning and technical reasoning, not a long-running team story. STAR answers need your own actions and supportable outcomes.
