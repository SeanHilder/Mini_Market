"""Transactional orders and stock, with cart version checks and safe retries."""

import hashlib
import secrets
from dataclasses import dataclass

from .carts import CartConflict, get_cart, read_cart


class CheckoutError(ValueError):
    """A customer-correctable validation or stock problem."""


@dataclass(frozen=True)
class OrderResult:
    reference: str
    order_id: int
    replayed: bool = False


def _write_order(db, cart, checkout_key, cart_id=None):
    """Caller owns the transaction. Acquire product locks in ascending ID order."""
    if not cart:
        raise CheckoutError("Your cart is empty. Add something before checking out.")
    items = []
    for product_id, quantity in sorted(cart.items(), key=lambda item: int(item[0])):
        if type(quantity) is not int or not 1 <= quantity <= 99:
            raise CheckoutError("Quantities must be whole numbers between 1 and 99.")
        product = db.execute("SELECT * FROM products WHERE id = ?" + db.lock_suffix, (product_id,)).fetchone()
        if product is None:
            raise CheckoutError("A product is no longer available. Please update your cart.")
        if product["stock"] < quantity:
            raise CheckoutError(f"Only {product['stock']} of {product['name']} available. Please update your cart.")
        items.append((product, quantity))
    total = sum(product["price_cents"] * quantity for product, quantity in items)
    reference = "MM-" + secrets.token_hex(12).upper()
    order_id = db.execute(
        "INSERT INTO orders (reference, checkout_key, total_cents, cart_id) VALUES (?, ?, ?, ?) RETURNING id",
        (reference, checkout_key, total, cart_id),
    ).fetchone()["id"]
    for product, quantity in items:
        db.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product["id"]))
        db.execute("INSERT INTO order_items (order_id, product_id, product_name, unit_price_cents, quantity) VALUES (?, ?, ?, ?, ?)",
            (order_id, product["id"], product["name"], product["price_cents"], quantity))
    return OrderResult(reference, order_id)


def place_order(db, cart, checkout_key):
    """Low-level service entry point for tests/tools without a browser cart."""
    try:
        db.begin_write()
        if db.postgres:
            # Serialise retries of the same key, without locking unrelated orders.
            lock_id = int.from_bytes(hashlib.sha256(checkout_key.encode()).digest()[:8], "big", signed=True)
            db.execute("SELECT pg_advisory_xact_lock(?)", (lock_id,))
        previous = db.execute("SELECT reference FROM orders WHERE checkout_key = ?", (checkout_key,)).fetchone()
        if previous:
            db.commit()
            return previous["reference"]
        result = _write_order(db, cart, checkout_key)
        db.commit()
        return result.reference
    except Exception:
        db.rollback()
        raise


def checkout_cart(db, cart_id, expected_version, checkout_key):
    """Lock the cart, check its version, and clear it in the order transaction."""
    try:
        db.begin_write()
        cart = get_cart(db, cart_id, lock=True)
        if cart is None:
            raise CartConflict("Your cart is no longer available. Reload the store.")
        previous = db.execute("SELECT id, reference FROM orders WHERE checkout_key = ? AND cart_id = ?", (checkout_key, cart_id)).fetchone()
        if previous:
            db.commit()
            return OrderResult(previous["reference"], previous["id"], replayed=True)
        if cart["version"] != expected_version or cart["checkout_key"] != checkout_key:
            raise CartConflict("This cart changed in another tab. Review the current cart before ordering.")
        result = _write_order(db, read_cart(db, cart_id), checkout_key, cart_id)
        db.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart_id,))
        db.execute("UPDATE carts SET version = version + 1, checkout_key = ? WHERE id = ?", (secrets.token_hex(32), cart_id))
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
