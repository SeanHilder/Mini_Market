"""Migrations receive a transaction-owned connection from the application's CLI."""

from alembic import context

connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=None, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
