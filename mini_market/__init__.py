"""Flask routes: translate browser requests into validated application actions."""

import os
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from . import db
from .checkout import CheckoutError, place_order


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=str(Path(app.instance_path) / "market.sqlite"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)

    @app.template_filter("money")
    def money(cents):
        return f"${cents // 100:,}.{cents % 100:02d}"

    @app.before_request
    def csrf_protection():
        session.setdefault("csrf_token", secrets.token_hex(32))
        session.setdefault("checkout_key", secrets.token_hex(32))
        if request.method == "POST":
            token = request.form.get("csrf_token", "")
            if not token.isascii() or not secrets.compare_digest(token, session["csrf_token"]):
                abort(400, description="Your form has expired. Reload the page and try again.")

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.context_processor
    def template_context():
        return {"cart_count": sum(session.get("cart", {}).values())}

    def cart_details():
        lines = []
        for product_id, quantity in session.get("cart", {}).items():
            product = db.get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if product:
                lines.append({"product": product, "quantity": quantity, "subtotal": quantity * product["price_cents"]})
        return lines, sum(line["subtotal"] for line in lines)

    def render_cart(error=None, status=200):
        lines, total = cart_details()
        return render_template("cart.html", lines=lines, total=total, error=error), status

    @app.get("/")
    def catalogue():
        products = db.get_db().execute("SELECT * FROM products ORDER BY id").fetchall()
        return render_template("catalogue.html", products=products)

    @app.get("/cart")
    def cart():
        return render_cart()

    @app.post("/cart/<int:product_id>")
    def update_cart(product_id):
        product = db.get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if product is None:
            abort(404)
        action = request.form.get("action")
        current = dict(session.get("cart", {}))
        if action == "remove":
            quantity = 0
        elif action == "add":
            quantity = current.get(str(product_id), 0) + 1
        elif action == "update":
            raw = request.form.get("quantity", "")
            if not 1 <= len(raw) <= 2 or not raw.isascii() or not raw.isdecimal() or not 1 <= int(raw) <= 99:
                return render_cart("Enter a whole-number quantity between 1 and 99.", 400)
            quantity = int(raw)
        else:
            abort(400, description="Unknown cart action.")
        if quantity > 99 or quantity > product["stock"]:
            return render_cart(f"Only {product['stock']} of {product['name']} available. Your cart has not changed.", 409)
        if quantity:
            current[str(product_id)] = quantity
        else:
            current.pop(str(product_id), None)
        session["cart"] = current
        session["checkout_key"] = secrets.token_hex(32)
        flash(f"{product['name']} {'removed from' if not quantity else 'updated in'} your cart.")
        return redirect(url_for("catalogue" if action == "add" else "cart"), code=303)

    @app.post("/checkout")
    def checkout():
        key = request.form.get("checkout_key", "")
        if not key.isascii() or not secrets.compare_digest(key, session["checkout_key"]):
            return render_cart("Your cart changed. Review it before placing your order.", 409)
        try:
            reference = place_order(db.get_db(), session.get("cart", {}), key)
        except CheckoutError as exc:
            return render_cart(str(exc), 409)
        except sqlite3.Error:
            app.logger.exception("Checkout database failure")
            return render_cart("We couldn't complete your order. Please try again. No payment was taken.", 503)
        session["cart"] = {}
        # Keep this key so a double click/retry resolves to the original order.
        # Any subsequent cart change creates a fresh key.
        return redirect(url_for("confirmation", reference=reference), code=303)

    @app.get("/orders/<reference>")
    def confirmation(reference):
        order = db.get_db().execute("SELECT * FROM orders WHERE reference = ?", (reference,)).fetchone()
        if order is None:
            abort(404)
        items = db.get_db().execute("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order["id"],)).fetchall()
        return render_template("confirmation.html", order=order, items=items)

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def request_error(error):
        return render_template("error.html", error=error), error.code

    return app
