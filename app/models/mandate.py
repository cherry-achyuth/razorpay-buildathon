"""Mandate domain model."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseSystemModel
from app.models.enums import MandateStatus

if TYPE_CHECKING:
    from app.models.merchant import Merchant
    from app.models.transaction import Transaction
    from app.models.user import User


class Mandate(BaseSystemModel):
    """Financial authorization contract defining bounded transaction parameters."""

    __tablename__ = "mandates"
    __table_args__ = (
        CheckConstraint(
            "max_transaction_amount > 0",
            name="ck_mandates_positive_max_amount",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_mandates_valid_date_range",
        ),
        CheckConstraint(
            "length(currency) = 3",
            name="ck_mandates_currency_format",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        doc="Optional merchant restriction; NULL allows any verified merchant.",
    )
    status: Mapped[MandateStatus] = mapped_column(
        SQLEnum(MandateStatus, native_enum=False, length=32),
        default=MandateStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        doc="ISO 4217 currency code (e.g. INR, USD).",
    )
    max_transaction_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        doc="Maximum exact monetary cap per single transaction.",
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

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="mandates")
    merchant: Mapped["Merchant | None"] = relationship(
        "Merchant", back_populates="mandates"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="mandate",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Mandate id={self.id} user_id={self.user_id} "
            f"max_amount={self.max_transaction_amount} {self.currency} "
            f"status={self.status}>"
        )
