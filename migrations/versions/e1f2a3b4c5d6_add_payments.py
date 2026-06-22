"""add payments table + order tip/discount/method + menu hsn

Additive: new payments table; tip_amount/discount_amount/discount_reason/
payment_method on orders; hsn_code on menu_items.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-18 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('tip_amount', sa.Numeric(10, 2), nullable=False, server_default='0'))
    op.add_column('orders', sa.Column('discount_amount', sa.Numeric(10, 2), nullable=False, server_default='0'))
    op.add_column('orders', sa.Column('discount_reason', sa.Text(), nullable=True))
    op.add_column('orders', sa.Column('payment_method', sa.String(), nullable=True))
    op.add_column('menu_items', sa.Column('hsn_code', sa.String(), nullable=True))

    op.create_table(
        'payments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('order_id', sa.String(), nullable=True),
        sa.Column('table_session_id', sa.String(), nullable=True),
        sa.Column('method', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('provider_order_id', sa.String(), nullable=True),
        sa.Column('provider_payment_id', sa.String(), nullable=True),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('tip_amount', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('discount_amount', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('refund_amount', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['table_session_id'], ['table_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payments_order_id', 'payments', ['order_id'])
    op.create_index('ix_payments_table_session_id', 'payments', ['table_session_id'])
    op.create_index('ix_payments_provider_order_id', 'payments', ['provider_order_id'])


def downgrade() -> None:
    op.drop_index('ix_payments_provider_order_id', table_name='payments')
    op.drop_index('ix_payments_table_session_id', table_name='payments')
    op.drop_index('ix_payments_order_id', table_name='payments')
    op.drop_table('payments')
    op.drop_column('menu_items', 'hsn_code')
    op.drop_column('orders', 'payment_method')
    op.drop_column('orders', 'discount_reason')
    op.drop_column('orders', 'discount_amount')
    op.drop_column('orders', 'tip_amount')
