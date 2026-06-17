"""concurrency: partial unique indexes for sessions + carts

Prevents the check-then-insert races the audit found:
  - at most ONE non-closed TableSession per table
  - at most ONE 'cart' order per customer (parcel)
  - at most ONE 'cart' order per table (dine-in)

Existing duplicates (from before these constraints) are first de-duplicated —
keep the most recent, close/cancel the rest — so the unique indexes can be
created. Data-preserving (only collapses already-invalid duplicate state); no
table/column drops.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. de-dupe existing invalid state, keeping the most recent row ---
    op.execute(
        """
        UPDATE table_sessions SET status = 'closed', closed_at = NOW()
        WHERE status != 'closed' AND id NOT IN (
            SELECT DISTINCT ON (table_id) id FROM table_sessions
            WHERE status != 'closed' ORDER BY table_id, opened_at DESC
        )
        """
    )
    op.execute(
        """
        UPDATE orders SET status = 'cancelled'
        WHERE status = 'cart' AND customer_id IS NOT NULL AND id NOT IN (
            SELECT DISTINCT ON (customer_id) id FROM orders
            WHERE status = 'cart' AND customer_id IS NOT NULL
            ORDER BY customer_id, created_at DESC
        )
        """
    )
    op.execute(
        """
        UPDATE orders SET status = 'cancelled'
        WHERE status = 'cart' AND table_id IS NOT NULL AND id NOT IN (
            SELECT DISTINCT ON (table_id) id FROM orders
            WHERE status = 'cart' AND table_id IS NOT NULL
            ORDER BY table_id, created_at DESC
        )
        """
    )

    # --- 2. partial unique indexes enforce the invariants going forward ---
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_open_session_per_table "
        "ON table_sessions (table_id) WHERE status != 'closed'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cart_per_customer "
        "ON orders (customer_id) WHERE status = 'cart' AND customer_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cart_per_table "
        "ON orders (table_id) WHERE status = 'cart' AND table_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_cart_per_table")
    op.execute("DROP INDEX IF EXISTS uq_cart_per_customer")
    op.execute("DROP INDEX IF EXISTS uq_open_session_per_table")
