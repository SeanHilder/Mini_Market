"""HTTP routes around versioned server carts and a transactional order service."""

import os
import secrets
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

from . import carts, db, observability
from .checkout import CheckoutError, checkout_cart


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("DATABASE_URL") or str(Path(app.instance_path) / "market.sqlite"),
        METRICS_TOKEN=os.environ.get("METRICS_TOKEN"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    observability.init_app(app)

    @app.template_filter("money")
    def money(cents):
        return f"${cents // 100:,}.{cents % 100:02d}"

    def refresh_cart():
        g.cart = carts.get_cart(db.get_db(), session["cart_id"])
        g.cart_items = carts.read_cart(db.get_db(), session["cart_id"])

    @app.before_request
    def browser_session():
        if request.endpoint in {"static", "metrics", "health", "ready"}:
            return
        session.setdefault("csrf_token", secrets.token_hex(32))
        if request.method == "POST":
            token = request.form.get("csrf_token", "")
            if not token.isascii() or not secrets.compare_digest(token, session["csrf_token"]):
                abort(400, description="Your form has expired. Reload the page and try again.")
        connection = db.get_db()
        cart_id = session.get("cart_id")
        if cart_id is None or carts.get_cart(connection, cart_id) is None:
            session["cart_id"] = carts.create_cart(connection)
        # Old cookie-held carts cannot safely participate in version checks.
        session.pop("cart", None)
        session.pop("checkout_key", None)
        refresh_cart()

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.context_processor
    def template_context():
        cart = getattr(g, "cart", None)
        return {
            "cart_count": sum(getattr(g, "cart_items", {}).values()),
            "cart_version": cart["version"] if cart else 0,
            "checkout_key": cart["checkout_key"] if cart else "",
        }

    def render_cart(error=None, status=200):
        refresh_cart()
        lines = []
        for product_id, quantity in g.cart_items.items():
            product = db.get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if product:
                lines.append({"product": product, "quantity": quantity, "subtotal": quantity * product["price_cents"]})
        return render_template("cart.html", lines=lines, total=sum(line["subtotal"] for line in lines), error=error), status

    def submitted_version():
        raw = request.form.get("cart_version", "")
        if not 1 <= len(raw) <= 10 or not raw.isascii() or not raw.isdecimal():
            abort(400, description="Missing or invalid cart version. Reload the page and try again.")
        return int(raw)

    @app.get("/")
    def catalogue():
        products = db.get_db().execute("SELECT * FROM products ORDER BY id").fetchall()
        return render_template("catalogue.html", products=products)

    @app.get("/cart")
    def cart():
        return render_cart()

    @app.post("/cart/<int:product_id>")
    def update_cart(product_id):
        version = submitted_version()
        action = request.form.get("action")
        quantity = None
        if action == "update":
            raw = request.form.get("quantity", "")
            if not 1 <= len(raw) <= 2 or not raw.isascii() or not raw.isdecimal():
                return render_cart("Enter a whole-number quantity between 1 and 99.", 400)
            quantity = int(raw)
        try:
            name = carts.mutate_cart(db.get_db(), session["cart_id"], version, product_id, action, quantity)
        except LookupError:
            abort(404)
        except carts.CartValidation as exc:
            return render_cart(str(exc), 400)
        except carts.CartConflict as exc:
            app.extensions["telemetry"]["cart_conflicts"].inc()
            return render_cart(str(exc), 409)
        flash(f"{name} {'removed from' if action == 'remove' else 'updated in'} your cart.")
        return redirect(url_for("catalogue" if action == "add" else "cart"), code=303)

    @app.post("/checkout")
    def checkout():
        version = submitted_version()
        key = request.form.get("checkout_key", "")
        if len(key) != 64 or not key.isascii():
            observability.checkout_event(app, "conflict")
            return render_cart("Your checkout form expired. Review your cart and try again.", 409)
        try:
            result = checkout_cart(db.get_db(), session["cart_id"], version, key)
        except (CheckoutError, carts.CartConflict) as exc:
            observability.checkout_event(app, "conflict")
            return render_cart(str(exc), 409)
        observability.checkout_event(app, "replayed" if result.replayed else "created", result.order_id)
        return redirect(url_for("confirmation", reference=result.reference), code=303)

    @app.get("/orders/<reference>")
    def confirmation(reference):
        order = db.get_db().execute("SELECT * FROM orders WHERE reference = ?", (reference,)).fetchone()
        if order is None:
            abort(404)
        items = db.get_db().execute("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order["id"],)).fetchall()
        return render_template("confirmation.html", order=order, items=items)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        # A connection alone is insufficient: require the expected migration.
        row = db.get_db().execute("SELECT version_num FROM alembic_version").fetchone()
        return ({"status": "ready"}, 200) if row and row["version_num"] == "0002" else ({"status": "not_ready"}, 503)

    def database_error(error):
        observability.emit(app, "database_error", error_type=type(error).__name__)
        if request.endpoint == "checkout":
            observability.checkout_event(app, "error")
        # Do not query again to render an error during a database outage.
        return "We couldn't complete this request. Please try again. No payment was taken.", 503

    for error_type in db.DATABASE_ERRORS:
        app.register_error_handler(error_type, database_error)

    @app.errorhandler(500)
    def internal_error(error):
        original = getattr(error, "original_exception", None)
        observability.emit(app, "internal_error", error_type=type(original).__name__)
        return "Something went wrong. Please try again or quote the X-Request-ID response header.", 500

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def request_error(error):
        return render_template("error.html", error=error), error.code

    return app
