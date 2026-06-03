"""add parcel customers and service areas

Pivots the platform to a public, parcel-only ordering line:
  - new ``customers`` table (auth-free, 4-digit code identity)
  - new ``service_areas`` allowlist (delivery sphere of influence)
  - parcel/delivery columns on ``orders`` + nullable ``user_id``
  - ``customer_id`` on ``chat_sessions`` + nullable ``user_id``

All changes are additive or relax nullability — no drops, no data movement,
so existing rows are preserved.

Revision ID: a1b2c3d4e5f6
Revises: 09f92a6c4618
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '09f92a6c4618'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'customers',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('address_line', sa.Text(), nullable=True),
        sa.Column('area', sa.String(), nullable=True),
        sa.Column('pincode', sa.String(), nullable=True),
        sa.Column('landmark', sa.String(), nullable=True),
        sa.Column('preferences', sa.Text(), nullable=True),
        sa.Column('allergies', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('order_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_order_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.UniqueConstraint('phone'),
    )
    op.create_index(op.f('ix_customers_code'), 'customers', ['code'], unique=False)
    op.create_index(op.f('ix_customers_phone'), 'customers', ['phone'], unique=False)

    op.create_table(
        'service_areas',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('pincode', sa.String(), nullable=True),
        sa.Column('aliases', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_service_areas_pincode'), 'service_areas', ['pincode'], unique=False)

    # --- orders: parcel/delivery columns + relax user_id ---
    op.add_column('orders', sa.Column('customer_id', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('order_type', sa.String(), nullable=False, server_default='parcel'))
    op.add_column('orders', sa.Column('contact_name', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('contact_phone', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('delivery_address', sa.Text(), nullable=True))
    op.add_column('orders', sa.Column('delivery_area', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('delivery_pincode', sa.String(), nullable=True))
    op.alter_column('orders', 'user_id', existing_type=sa.String(), nullable=True)
    op.create_index(op.f('ix_orders_customer_id'), 'orders', ['customer_id'], unique=False)
    op.create_foreign_key(
        'fk_orders_customer_id', 'orders', 'customers', ['customer_id'], ['id']
    )

    # --- chat_sessions: customer_id + relax user_id ---
    op.add_column('chat_sessions', sa.Column('customer_id', sa.String(), nullable=True))
    op.alter_column('chat_sessions', 'user_id', existing_type=sa.String(), nullable=True)
    op.create_index(op.f('ix_chat_sessions_customer_id'), 'chat_sessions', ['customer_id'], unique=False)
    op.create_foreign_key(
        'fk_chat_sessions_customer_id', 'chat_sessions', 'customers', ['customer_id'], ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_chat_sessions_customer_id', 'chat_sessions', type_='foreignkey')
    op.drop_index(op.f('ix_chat_sessions_customer_id'), table_name='chat_sessions')
    op.alter_column('chat_sessions', 'user_id', existing_type=sa.String(), nullable=False)
    op.drop_column('chat_sessions', 'customer_id')

    op.drop_constraint('fk_orders_customer_id', 'orders', type_='foreignkey')
    op.drop_index(op.f('ix_orders_customer_id'), table_name='orders')
    op.alter_column('orders', 'user_id', existing_type=sa.String(), nullable=False)
    op.drop_column('orders', 'delivery_pincode')
    op.drop_column('orders', 'delivery_area')
    op.drop_column('orders', 'delivery_address')
    op.drop_column('orders', 'contact_phone')
    op.drop_column('orders', 'contact_name')
    op.drop_column('orders', 'order_type')
    op.drop_column('orders', 'customer_id')

    op.drop_index(op.f('ix_service_areas_pincode'), table_name='service_areas')
    op.drop_table('service_areas')
    op.drop_index(op.f('ix_customers_phone'), table_name='customers')
    op.drop_index(op.f('ix_customers_code'), table_name='customers')
    op.drop_table('customers')
