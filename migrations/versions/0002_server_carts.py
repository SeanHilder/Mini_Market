"""Persistent carts, optimistic versions, and ownership of checkout retries."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None


def upgrade():
    op.create_table("carts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checkout_key", sa.Text, nullable=False, unique=True),
        sa.Column("created_at", sa.Text, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("version >= 0", name="cart_version_nonnegative"))
    op.create_table("cart_items",
        sa.Column("cart_id", sa.Text, sa.ForeignKey("carts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.CheckConstraint("quantity BETWEEN 1 AND 99", name="cart_quantity_valid"))
    # Nullable so historical orders retain their receipts without an invented cart.
    with op.batch_alter_table("orders", naming_convention={"ck": "ck_%(table_name)s_%(column_0_name)s"}) as batch:
        batch.add_column(sa.Column("cart_id", sa.Text))
        batch.create_foreign_key("orders_cart_fk", "carts", ["cart_id"], ["id"])
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])


def downgrade():
    raise RuntimeError("Destructive downgrade is intentionally unsupported; restore a backup instead.")
