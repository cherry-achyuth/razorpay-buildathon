"""initial baseline schema

Revision ID: 0001_initial_baseline
Revises:
Create Date: 2026-08-23 12:00:00.000000 UTC

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_metadata",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_metadata")),
    )
    op.create_index(
        op.f("ix_system_metadata_key"),
        "system_metadata",
        ["key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_system_metadata_key"), table_name="system_metadata")
    op.drop_table("system_metadata")
