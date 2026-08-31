# Migration policy

Alembic revisions are the schema source of truth. `python -m flask --app app migrate-db` supplies a SQLAlchemy connection and applies `upgrade head` in a transaction. SQLite uses explicit transaction control so DDL is transactional too. Revision `0002` names reflected legacy checks so the order-total constraint survives SQLite table reconstruction.

To extend the schema, add a new revision file with a unique `revision`, the current head as `down_revision`, and dialect-portable Alembic operations. Do not edit previously deployed revisions. Add preservation tests and run on SQLite and PostgreSQL before release. Use stable constraint names; consider SQLite batch-table rebuilds and PostgreSQL locking when designing changes.

Back up first, stop the application for this small demo, run the migration once and then restart it. The runner supports fresh databases and the recognised original three-table prototype. Downgrades intentionally fail because dropping carts or historical records would be destructive. Recovery is via a tested backup, not an automatic downgrade. Unknown legacy schemas require manual review.

`tests/fixtures/legacy_schema.sql` is a test snapshot of the original implementation, not an initialisation command.
