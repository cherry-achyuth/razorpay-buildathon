"""semantic memory embeddings

Revision ID: 0005_semantic_memory_embeddings
Revises: 0004_decision_memory_foundation
Create Date: 2026-08-23 23:20:00.000000 UTC

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_semantic_memory_embeddings"
down_revision: str | None = "0004_decision_memory_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enable pgvector extension if running on PostgreSQL
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Add embedding column to decision_memories
    op.add_column(
        "decision_memories",
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.Vector(384),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # 1. Drop embedding column from decision_memories
    op.drop_column("decision_memories", "embedding")
