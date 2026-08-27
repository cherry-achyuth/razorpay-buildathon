"""Transaction domain model."""

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
from app.models.enums import TransactionStatus, TransactionType

if TYPE_CHECKING:
    from app.models.decision import Decision
    from app.models.mandate import Mandate
    from app.models.merchant import Merchant
    from app.models.user import User


class Transaction(BaseSystemModel):
    """Immutable record of an actual financial event or recorded execution attempt."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="ck_transactions_positive_amount",
        ),
        CheckConstraint(
            "length(currency) = 3",
            name="ck_transactions_currency_format",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mandate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mandates.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        doc="Optional mandate under which this transaction was initiated.",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        doc="Exact monetary quantity.",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        doc="ISO 4217 currency code (e.g. INR, USD).",
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        SQLEnum(TransactionType, native_enum=False, length=32),
        default=TransactionType.PURCHASE,
        nullable=False,
        index=True,
    )
    status: Mapped[TransactionStatus] = mapped_column(
        SQLEnum(TransactionStatus, native_enum=False, length=32),
        default=TransactionStatus.PENDING,
        nullable=False,
        index=True,
    )
    external_reference: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
        doc="External gateway or provider reference ID.",
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
        index=True,
        doc="Client-supplied key to prevent duplicate payment executions.",
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="transactions")
    merchant: Mapped["Merchant"] = relationship(
        "Merchant", back_populates="transactions"
    )
    mandate: Mapped["Mandate | None"] = relationship(
        "Mandate", back_populates="transactions"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        "Decision",
        back_populates="transaction",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} amount={self.amount} {self.currency} "
            f"status={self.status}>"
        )
