"""add staff role to users

Additive: one new column ``users.role`` (owner | manager | cashier | waiter |
chef | none) with server default 'manager'. Existing admins are promoted to
'owner'; existing non-admins were all public registrants (staff didn't exist
yet) so they become 'none' (no back-office access). is_admin stays a compat flag.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('role', sa.String(), nullable=False, server_default='manager'),
    )
    # Backfill from the existing is_admin flag. Non-admins were public
    # registrants (no staff concept existed), so they get no back-office access.
    op.execute("UPDATE users SET role = 'owner' WHERE is_admin = true")
    op.execute("UPDATE users SET role = 'none' WHERE is_admin = false")


def downgrade() -> None:
    op.drop_column('users', 'role')
