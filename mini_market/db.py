"""SQLite connections and an explicit, repeatable demo-data command."""

import sqlite3
from pathlib import Path

import click
from flask import current_app, g


def connect(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def init_db():
    db = get_db()
    db.executescript(Path(__file__).with_name("schema.sql").read_text())
    products = [
        ("Everyday tote", "A sturdy cotton companion for your daily essentials.", "Accessories", 2400, 12, "tote", "ET"),
        ("Studio notebook", "Room for the next idea. 160 dotted pages.", "Stationery", 1800, 18, "notebook", "SN"),
        ("Morning mug", "A ceramic favourite for slower mornings.", "Home", 2200, 8, "mug", "MM"),
        ("Trail bottle", "Keep your everyday adventures hydrated. 750 ml.", "Outdoors", 3200, 6, "bottle", "TB"),
        ("Desk planter", "A little space for something green. Plant not included.", "Home", 1600, 1, "planter", "DP"),
        ("Weekend cap", "An easy-going classic in soft cotton.", "Accessories", 2600, 0, "cap", "WC"),
    ]
    db.executemany(
        "INSERT INTO products (name, description, category, price_cents, stock, illustration, initials) VALUES (?, ?, ?, ?, ?, ?, ?)",
        products,
    )
    db.commit()


def init_app(app):
    @app.teardown_appcontext
    def close_db(exception=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.cli.command("init-db")
    @click.option("--reset", is_flag=True, help="Delete existing local orders and reset demo stock.")
    def init_db_command(reset):
        if Path(app.config["DATABASE"]).exists() and not reset:
            raise click.ClickException("Database exists. Use --reset only to deliberately erase demo data.")
        init_db()
        click.echo("Demo database ready: six products, no orders.")
