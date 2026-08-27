"""decision memory foundation tables

Revision ID: 0004_decision_memory_foundation
Revises: 0003_idempotency_records
Create Date: 2026-08-23 22:50:00.000000 UTC

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_decision_memory_foundation"
down_revision: str | None = "0003_idempotency_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create decision_memories table
    op.create_table(
        "decision_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("relevance", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("structured_data", sa.JSON(), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_decision_memories_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision_memories")),
    )
    op.create_index(
        op.f("ix_decision_memories_user_id"),
        "decision_memories",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_memories_memory_type"),
        "decision_memories",
        ["memory_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_memories_relevance"),
        "decision_memories",
        ["relevance"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_memories_status"),
        "decision_memories",
        ["status"],
        unique=False,
    )

    # 2. Create decision_memory_sources table
    op.create_table(
        "decision_memory_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["decision_memories.id"],
            name=op.f("fk_decision_memory_sources_memory_id_decision_memories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision_memory_sources")),
        sa.UniqueConstraint(
            "memory_id",
            "source_type",
            "source_id",
            name="uq_decision_memory_source",
        ),
    )
    op.create_index(
        op.f("ix_decision_memory_sources_memory_id"),
        "decision_memory_sources",
        ["memory_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_memory_sources_source_type"),
        "decision_memory_sources",
        ["source_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_memory_sources_source_id"),
        "decision_memory_sources",
        ["source_id"],
        unique=False,
    )


def downgrade() -> None:
    # 1. Drop decision_memory_sources
    op.drop_index(
        op.f("ix_decision_memory_sources_source_id"),
        table_name="decision_memory_sources",
    )
    op.drop_index(
        op.f("ix_decision_memory_sources_source_type"),
        table_name="decision_memory_sources",
    )
    op.drop_index(
        op.f("ix_decision_memory_sources_memory_id"),
        table_name="decision_memory_sources",
    )
    op.drop_table("decision_memory_sources")

    # 2. Drop decision_memories
    op.drop_index(
        op.f("ix_decision_memories_status"),
        table_name="decision_memories",
    )
    op.drop_index(
        op.f("ix_decision_memories_relevance"),
        table_name="decision_memories",
    )
    op.drop_index(
        op.f("ix_decision_memories_memory_type"),
        table_name="decision_memories",
    )
    op.drop_index(
        op.f("ix_decision_memories_user_id"),
        table_name="decision_memories",
    )
    op.drop_table("decision_memories")
