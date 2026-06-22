"""add order ops + audit (void/refund reasons, item status, audit_logs)

Additive: cancellation/refund fields on orders, per-item status + void_reason on
order_items, and a new audit_logs table. No data movement.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-18 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('cancellation_reason', sa.Text(), nullable=True))
    op.add_column('orders', sa.Column('refunded', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('orders', sa.Column('refund_reason', sa.Text(), nullable=True))
    op.add_column('orders', sa.Column('refunded_at', sa.DateTime(), nullable=True))

    op.add_column('order_items', sa.Column('status', sa.String(), nullable=False, server_default='pending'))
    op.add_column('order_items', sa.Column('void_reason', sa.Text(), nullable=True))

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('actor_user_id', sa.String(), nullable=True),
        sa.Column('actor_email', sa.String(), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('entity', sa.String(), nullable=False),
        sa.Column('entity_id', sa.String(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_actor_user_id', 'audit_logs', ['actor_user_id'])
    op.create_index('ix_audit_logs_entity_id', 'audit_logs', ['entity_id'])


def downgrade() -> None:
    op.drop_index('ix_audit_logs_entity_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor_user_id', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_column('order_items', 'void_reason')
    op.drop_column('order_items', 'status')
    op.drop_column('orders', 'refunded_at')
    op.drop_column('orders', 'refund_reason')
    op.drop_column('orders', 'refunded')
    op.drop_column('orders', 'cancellation_reason')
