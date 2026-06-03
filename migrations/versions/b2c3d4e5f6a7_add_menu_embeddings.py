"""add menu embeddings (pgvector)

Adds a 1024-dim ``embedding`` column to menu_items for semantic search, plus a
cosine HNSW index. Enables the pgvector extension first. Additive only.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-02 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep in sync with config.EMBEDDING_DIM (mistral-embed = 1024).
EMBEDDING_DIM = 1024


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        'menu_items',
        sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=True),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_menu_items_embedding "
        "ON menu_items USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_menu_items_embedding")
    op.drop_column('menu_items', 'embedding')
