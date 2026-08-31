"""Original catalogue and orders; shared SQLite/PostgreSQL schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = depends_on = None


def upgrade():
    op.create_table("products",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("stock", sa.Integer, nullable=False),
        sa.Column("illustration", sa.Text, nullable=False),
        sa.Column("initials", sa.Text, nullable=False),
        sa.CheckConstraint("price_cents >= 0", name="product_price_nonnegative"),
        sa.CheckConstraint("stock >= 0", name="product_stock_nonnegative"))
    op.create_table("orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("reference", sa.Text, nullable=False, unique=True),
        sa.Column("checkout_key", sa.Text, nullable=False, unique=True),
        sa.Column("total_cents", sa.Integer, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("total_cents >= 0", name="order_total_nonnegative"))
    op.create_table("order_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("product_name", sa.Text, nullable=False),
        sa.Column("unit_price_cents", sa.Integer, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.CheckConstraint("unit_price_cents >= 0", name="item_price_nonnegative"),
        sa.CheckConstraint("quantity BETWEEN 1 AND 99", name="item_quantity_valid"),
        sa.UniqueConstraint("order_id", "product_id"))


def downgrade():
    raise RuntimeError("Destructive downgrade is intentionally unsupported; restore a backup instead.")
