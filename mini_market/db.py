"""Small DB-API boundary for SQLite and PostgreSQL; Alembic owns the schema."""

import sqlite3
from pathlib import Path

import click
import psycopg
from flask import current_app, g

from .migrations import upgrade

DATABASE_ERRORS = (sqlite3.Error, psycopg.Error)


class Record(dict):
    """Match sqlite3.Row's named and positional reads on PostgreSQL."""
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def record_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Record(zip(names, values))


def database_url(value):
    value = str(value)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+psycopg://", 1)
    if "://" in value:
        return value
    return "sqlite:///" + str(Path(value).resolve()).replace("\\", "/")


class Database:
    """Translate bound placeholders only; application SQL remains visible.

    SQL must be developer-authored: question marks denote bind parameters,
    never literal text. Values are always passed separately to the driver.
    """
    def __init__(self, value):
        self.url = database_url(value)
        self.postgres = self.url.startswith("postgresql")
        self.lock_suffix = " FOR UPDATE" if self.postgres else ""
        if self.postgres:
            self.raw = psycopg.connect(self.url.replace("postgresql+psycopg://", "postgresql://", 1),
                autocommit=True, row_factory=record_factory, connect_timeout=5)
            self.raw.execute("SET statement_timeout = '15s'")
            self.raw.execute("SET lock_timeout = '10s'")
        else:
            path = self.url.removeprefix("sqlite:///")
            self.raw = sqlite3.connect(path, timeout=10)
            self.raw.row_factory = sqlite3.Row
            self.raw.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql, parameters=()):
        return self.raw.execute(sql.replace("?", "%s") if self.postgres else sql, parameters)

    def executemany(self, sql, rows):
        cursor = self.raw.cursor()
        cursor.executemany(sql.replace("?", "%s") if self.postgres else sql, rows)
        return cursor

    def executescript(self, sql):
        if self.postgres:
            return self.raw.execute(sql)
        return self.raw.executescript(sql)

    def begin_write(self):
        self.execute("BEGIN" if self.postgres else "BEGIN IMMEDIATE")

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def connect(value):
    return Database(value)


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def seed_demo(connection):
    products = [
        ("Everyday tote", "A sturdy cotton companion for your daily essentials.", "Accessories", 2400, 12, "tote", "ET"),
        ("Studio notebook", "Room for the next idea. 160 dotted pages.", "Stationery", 1800, 18, "notebook", "SN"),
        ("Morning mug", "A ceramic favourite for slower mornings.", "Home", 2200, 8, "mug", "MM"),
        ("Trail bottle", "Keep your everyday adventures hydrated. 750 ml.", "Outdoors", 3200, 6, "bottle", "TB"),
        ("Desk planter", "A little space for something green. Plant not included.", "Home", 1600, 1, "planter", "DP"),
        ("Weekend cap", "An easy-going classic in soft cotton.", "Accessories", 2600, 0, "cap", "WC"),
    ]
    connection.executemany("INSERT INTO products (name, description, category, price_cents, stock, illustration, initials) VALUES (?, ?, ?, ?, ?, ?, ?)", products)


def init_db(reset=False):
    upgrade(database_url(current_app.config["DATABASE"]))
    connection = get_db()
    try:
        connection.begin_write()
        if reset:
            for table in ("order_items", "orders", "cart_items", "carts", "products"):
                connection.execute(f"DELETE FROM {table}")
            if connection.postgres:
                # Reset only the three demo identity sequences after explicit --reset.
                for table in ("products", "orders", "order_items"):
                    connection.execute(f"ALTER SEQUENCE {table}_id_seq RESTART WITH 1")
        if connection.execute("SELECT id FROM products LIMIT 1").fetchone():
            raise click.ClickException("Database already has products; use migrate-db to upgrade or --reset to erase demo data.")
        seed_demo(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def init_app(app):
    @app.teardown_appcontext
    def close_db(exception=None):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.cli.command("init-db")
    @click.option("--reset", is_flag=True, help="Erase local demo orders and carts, and reset stock.")
    def init_db_command(reset):
        init_db(reset=reset)
        click.echo("Schema current; demo products ready.")

    @app.cli.command("migrate-db")
    def migrate_db_command():
        upgrade(database_url(app.config["DATABASE"]))
        click.echo("Schema upgraded without deleting orders or products.")
