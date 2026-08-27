"""two tier policy limits

Revision ID: 0007_two_tier_policy_limits
Revises: 0006_tamper_evident_audit_log
Create Date: 2026-08-27 23:00:00.000000 UTC

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_two_tier_policy_limits"
down_revision: str | None = "0006_tamper_evident_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "policies",
        sa.Column(
            "hard_limit_amount",
            sa.Numeric(18, 4),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("policies", "hard_limit_amount")
