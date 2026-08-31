"""Persistent cart state with atomic version checks for competing browser tabs."""

import secrets


class CartConflict(ValueError):
    pass


class CartValidation(ValueError):
    pass


def create_cart(db):
    cart_id = secrets.token_hex(32)
    db.execute("INSERT INTO carts (id, checkout_key) VALUES (?, ?)", (cart_id, secrets.token_hex(32)))
    db.commit()
    return cart_id


def get_cart(db, cart_id, lock=False):
    return db.execute("SELECT * FROM carts WHERE id = ?" + (db.lock_suffix if lock else ""), (cart_id,)).fetchone()


def read_cart(db, cart_id):
    return {str(row["product_id"]): row["quantity"] for row in db.execute(
        "SELECT product_id, quantity FROM cart_items WHERE cart_id = ? ORDER BY product_id", (cart_id,)
    ).fetchall()}


def mutate_cart(db, cart_id, expected_version, product_id, action, quantity=None):
    try:
        db.begin_write()
        cart = get_cart(db, cart_id, lock=True)
        if cart is None or cart["version"] != expected_version:
            raise CartConflict("This cart changed in another tab. Review the current cart and try again.")
        product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if product is None:
            raise LookupError("Product not found")
        current = read_cart(db, cart_id)
        if action == "add":
            quantity = current.get(str(product_id), 0) + 1
        elif action == "remove":
            quantity = 0
        elif action != "update":
            raise CartValidation("Unknown cart action.")
        if type(quantity) is not int or not 0 <= quantity <= 99 or (action == "update" and quantity == 0):
            raise CartValidation("Enter a whole-number quantity between 1 and 99.")
        if quantity > product["stock"]:
            raise CartConflict(f"Only {product['stock']} of {product['name']} available. Your cart has not changed.")
        db.execute("DELETE FROM cart_items WHERE cart_id = ? AND product_id = ?", (cart_id, product_id))
        if quantity:
            db.execute("INSERT INTO cart_items (cart_id, product_id, quantity) VALUES (?, ?, ?)", (cart_id, product_id, quantity))
        updated = db.execute("UPDATE carts SET version = version + 1, checkout_key = ? WHERE id = ? AND version = ?",
            (secrets.token_hex(32), cart_id, expected_version))
        if updated.rowcount != 1:
            raise CartConflict("This cart changed in another tab. Please review it.")
        db.commit()
        return product["name"]
    except Exception:
        db.rollback()
        raise
