"""Order rules independent of HTTP, so failures and concurrency are testable."""

import secrets


class CheckoutError(ValueError):
    """A customer-correctable validation or stock problem."""


def place_order(db, cart, checkout_key):
    """Commit a whole order or nothing; retrying the same key returns the same order.

    BEGIN IMMEDIATE acquires SQLite's write reservation before reading stock.
    Other writers wait, then see the committed stock. This is suitable for a
    small SQLite application, not a claim of high-throughput scalability.
    """
    try:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT reference FROM orders WHERE checkout_key = ?", (checkout_key,)).fetchone()
        if previous:
            db.commit()
            return previous["reference"]
        if not cart:
            raise CheckoutError("Your cart is empty. Add something before checking out.")
        items = []
        for product_id, quantity in cart.items():
            if type(quantity) is not int or not 1 <= quantity <= 99:
                raise CheckoutError("Quantities must be whole numbers between 1 and 99.")
            product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if product is None:
                raise CheckoutError("A product is no longer available. Please update your cart.")
            if product["stock"] < quantity:
                raise CheckoutError(f"Only {product['stock']} of {product['name']} available. Please update your cart.")
            items.append((product, quantity))
        total = sum(product["price_cents"] * quantity for product, quantity in items)
        reference = "MM-" + secrets.token_hex(12).upper()
        order_id = db.execute(
            "INSERT INTO orders (reference, checkout_key, total_cents) VALUES (?, ?, ?)",
            (reference, checkout_key, total),
        ).lastrowid
        for product, quantity in items:
            db.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product["id"]))
            db.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, unit_price_cents, quantity) VALUES (?, ?, ?, ?, ?)",
                (order_id, product["id"], product["name"], product["price_cents"], quantity),
            )
        db.commit()
        return reference
    except Exception:
        db.rollback()
        raise
