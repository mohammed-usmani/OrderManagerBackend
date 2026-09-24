"""add payments.discount_reason

Additive: a nullable column so a staff discount's reason is kept with the
payment (table-session settles have no single order to hold it).

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-24 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('payments', sa.Column('discount_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('payments', 'discount_reason')
