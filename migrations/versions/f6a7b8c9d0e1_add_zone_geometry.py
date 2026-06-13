"""add zone geometry (floor-plan regions)

Zones become drawable rectangles on the floor-plan canvas: adds pos_x/pos_y
(top-left) + width/height to ``dining_zones``, then backfills existing zones into
a tidy non-overlapping tile grid (by display_order) so they're visible at once.

Additive only — four NOT NULL columns with server defaults + a data-preserving
backfill UPDATE. No drops.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-13 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dining_zones', sa.Column('pos_x', sa.Integer(), nullable=False, server_default='40'))
    op.add_column('dining_zones', sa.Column('pos_y', sa.Integer(), nullable=False, server_default='40'))
    op.add_column('dining_zones', sa.Column('width', sa.Integer(), nullable=False, server_default='320'))
    op.add_column('dining_zones', sa.Column('height', sa.Integer(), nullable=False, server_default='220'))

    # Tile existing zones into a 3-wide grid so they don't all overlap.
    op.execute(
        """
        UPDATE dining_zones SET
          pos_x = 40 + (COALESCE(display_order, 0) % 3) * 330,
          pos_y = 40 + (COALESCE(display_order, 0) / 3) * 250,
          width = 300,
          height = 220
        """
    )


def downgrade() -> None:
    op.drop_column('dining_zones', 'height')
    op.drop_column('dining_zones', 'width')
    op.drop_column('dining_zones', 'pos_y')
    op.drop_column('dining_zones', 'pos_x')
