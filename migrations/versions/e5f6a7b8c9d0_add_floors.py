"""add floors hierarchy + table shape + order floor snapshot

Introduces the Floor level above zones (Floor → Zone → Table):
  - new ``floors`` table (storeys: Ground / Rooftop …)
  - ``dining_zones.floor_id`` FK (nullable) + backfill existing zones onto a
    default "Ground Floor"
  - ``restaurant_tables.shape`` (round|square|rect) for the floor-plan canvas
    (pos_x/pos_y already exist)
  - ``orders.floor_name`` frozen snapshot (for by-floor analytics / KDS)

Additive only — new table + nullable/defaulted columns + a data-preserving
backfill UPDATE. No drops of live data.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Deterministic id for the default floor existing zones are backfilled onto.
DEFAULT_FLOOR_ID = "00000000-0000-0000-0000-0000000000f1"


def upgrade() -> None:
    op.create_table(
        'floors',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('width', sa.Integer(), nullable=False, server_default='1000'),
        sa.Column('height', sa.Integer(), nullable=False, server_default='640'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- dining_zones: floor_id FK ---
    op.add_column('dining_zones', sa.Column('floor_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_dining_zones_floor_id'), 'dining_zones', ['floor_id'], unique=False)
    op.create_foreign_key(
        'fk_dining_zones_floor_id', 'dining_zones', 'floors', ['floor_id'], ['id']
    )

    # --- restaurant_tables: shape ---
    op.add_column(
        'restaurant_tables',
        sa.Column('shape', sa.String(), nullable=False, server_default='round'),
    )

    # --- orders: floor snapshot ---
    op.add_column('orders', sa.Column('floor_name', sa.String(), nullable=True))

    # --- backfill: default Ground Floor + attach existing zones ---
    op.execute(
        f"""
        INSERT INTO floors (id, name, display_order, active, width, height, created_at)
        VALUES ('{DEFAULT_FLOOR_ID}', 'Ground Floor', 0, true, 1000, 640, NOW())
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        f"UPDATE dining_zones SET floor_id = '{DEFAULT_FLOOR_ID}' WHERE floor_id IS NULL"
    )


def downgrade() -> None:
    op.drop_column('orders', 'floor_name')
    op.drop_column('restaurant_tables', 'shape')
    op.drop_constraint('fk_dining_zones_floor_id', 'dining_zones', type_='foreignkey')
    op.drop_index(op.f('ix_dining_zones_floor_id'), table_name='dining_zones')
    op.drop_column('dining_zones', 'floor_id')
    op.drop_table('floors')
