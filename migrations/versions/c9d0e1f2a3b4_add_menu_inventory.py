"""add inventory / 86-ing to menu items

Additive: track_stock (bool), stock_qty (int, nullable), is_86 (bool) on
menu_items. No data movement.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-18 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('menu_items', sa.Column('track_stock', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('menu_items', sa.Column('stock_qty', sa.Integer(), nullable=True))
    op.add_column('menu_items', sa.Column('is_86', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('menu_items', 'is_86')
    op.drop_column('menu_items', 'stock_qty')
    op.drop_column('menu_items', 'track_stock')
