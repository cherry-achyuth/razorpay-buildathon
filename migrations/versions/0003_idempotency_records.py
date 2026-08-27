"""idempotency records table

Revision ID: 0003_idempotency_records
Revises: 0002_financial_domain_models
Create Date: 2026-08-23 22:20:00.000000 UTC

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_idempotency_records"
down_revision: str | None = "0002_financial_domain_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
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
            name=op.f("fk_idempotency_records_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_records")),
    )
    op.create_index(
        op.f("ix_idempotency_records_key"),
        "idempotency_records",
        ["key"],
        unique=True,
    )
    op.create_index(
        op.f("ix_idempotency_records_user_id"),
        "idempotency_records",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_idempotency_records_request_hash"),
        "idempotency_records",
        ["request_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_idempotency_records_request_hash"),
        table_name="idempotency_records",
    )
    op.drop_index(
        op.f("ix_idempotency_records_user_id"),
        table_name="idempotency_records",
    )
    op.drop_index(
        op.f("ix_idempotency_records_key"),
        table_name="idempotency_records",
    )
    op.drop_table("idempotency_records")
