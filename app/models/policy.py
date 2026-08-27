"""Policy domain model."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseSystemModel
from app.models.enums import PolicyStatus, PolicyType

if TYPE_CHECKING:
    from app.models.user import User


class Policy(BaseSystemModel):
    """Spending boundary, budget cap, or merchant restriction policy."""

    __tablename__ = "policies"
    __table_args__ = (
        CheckConstraint(
            "limit_amount IS NULL OR limit_amount >= 0",
            name="ck_policies_positive_limit_amount",
        ),
        CheckConstraint(
            "hard_limit_amount IS NULL OR hard_limit_amount >= 0",
            name="ck_policies_positive_hard_limit_amount",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_policies_valid_date_range",
        ),
        CheckConstraint(
            "currency IS NULL OR length(currency) = 3",
            name="ck_policies_currency_format",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    policy_type: Mapped[PolicyType] = mapped_column(
        SQLEnum(PolicyType, native_enum=False, length=32),
        nullable=False,
        index=True,
    )
    status: Mapped[PolicyStatus] = mapped_column(
        SQLEnum(PolicyStatus, native_enum=False, length=32),
        default=PolicyStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    currency: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
        doc="ISO 4217 currency code if policy is monetary.",
    )
    limit_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=True,
        doc="Soft monetary constraint amount (routine threshold).",
    )
    hard_limit_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=True,
        doc="Absolute hard spend ceiling that always blocks unconditionally.",
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rules: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Structured policy rule specifications.",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="policies")

    def __repr__(self) -> str:
        return (
            f"<Policy id={self.id} name={self.name!r} type={self.policy_type} "
            f"status={self.status}>"
        )
