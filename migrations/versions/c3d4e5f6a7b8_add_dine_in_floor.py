"""add dine-in floor: zones, tables, table sessions + order columns

Introduces dine-in alongside the existing parcel flow:
  - ``dining_zones``       — rooms/sections; ``is_ac`` drives the AC surcharge
  - ``restaurant_tables``  — tables on the floor, each with a unique QR token
  - ``table_sessions``     — one running tab per dining visit
  - ``orders`` gains dine-in linkage (table_id, table_session_id), a zone
    snapshot (zone_name, is_ac), a frozen bill snapshot (charges_json, total),
    and lifecycle timestamps (served_at, ready_at, delivered_at).

All changes are additive — new tables and nullable columns only. No drops, no
data movement; existing parcel rows are untouched. Status-value remapping to the
new lifecycle is handled separately by the lifecycle engine (Phase 2).

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'dining_zones',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('is_ac', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'restaurant_tables',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('zone_id', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('seats', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('pos_x', sa.Integer(), nullable=True),
        sa.Column('pos_y', sa.Integer(), nullable=True),
        sa.Column('qr_token', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='free'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['zone_id'], ['dining_zones.id'], name='fk_restaurant_tables_zone_id'),
        sa.UniqueConstraint('qr_token'),
    )
    op.create_index(op.f('ix_restaurant_tables_zone_id'), 'restaurant_tables', ['zone_id'], unique=False)
    op.create_index(op.f('ix_restaurant_tables_qr_token'), 'restaurant_tables', ['qr_token'], unique=False)

    op.create_table(
        'table_sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('table_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='open'),
        sa.Column('party_size', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('opened_at', sa.DateTime(), nullable=False),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['table_id'], ['restaurant_tables.id'], name='fk_table_sessions_table_id'),
    )
    op.create_index(op.f('ix_table_sessions_table_id'), 'table_sessions', ['table_id'], unique=False)

    # --- orders: dine-in linkage, zone + bill snapshots, lifecycle timestamps ---
    op.add_column('orders', sa.Column('table_id', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('table_session_id', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('zone_name', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('is_ac', sa.Boolean(), nullable=True))
    op.add_column('orders', sa.Column('charges_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('orders', sa.Column('total', sa.Numeric(10, 2), nullable=True))
    op.add_column('orders', sa.Column('served_at', sa.DateTime(), nullable=True))
    op.add_column('orders', sa.Column('ready_at', sa.DateTime(), nullable=True))
    op.add_column('orders', sa.Column('delivered_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_orders_table_id'), 'orders', ['table_id'], unique=False)
    op.create_index(op.f('ix_orders_table_session_id'), 'orders', ['table_session_id'], unique=False)
    op.create_foreign_key(
        'fk_orders_table_id', 'orders', 'restaurant_tables', ['table_id'], ['id']
    )
    op.create_foreign_key(
        'fk_orders_table_session_id', 'orders', 'table_sessions', ['table_session_id'], ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_orders_table_session_id', 'orders', type_='foreignkey')
    op.drop_constraint('fk_orders_table_id', 'orders', type_='foreignkey')
    op.drop_index(op.f('ix_orders_table_session_id'), table_name='orders')
    op.drop_index(op.f('ix_orders_table_id'), table_name='orders')
    op.drop_column('orders', 'delivered_at')
    op.drop_column('orders', 'ready_at')
    op.drop_column('orders', 'served_at')
    op.drop_column('orders', 'total')
    op.drop_column('orders', 'charges_json')
    op.drop_column('orders', 'is_ac')
    op.drop_column('orders', 'zone_name')
    op.drop_column('orders', 'table_session_id')
    op.drop_column('orders', 'table_id')

    op.drop_index(op.f('ix_table_sessions_table_id'), table_name='table_sessions')
    op.drop_table('table_sessions')
    op.drop_index(op.f('ix_restaurant_tables_qr_token'), table_name='restaurant_tables')
    op.drop_index(op.f('ix_restaurant_tables_zone_id'), table_name='restaurant_tables')
    op.drop_table('restaurant_tables')
    op.drop_table('dining_zones')
