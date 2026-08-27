"""Decision domain model."""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseSystemModel
from app.models.enums import DecisionOutcome

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.user import User


class Decision(BaseSystemModel):
    """Historical audit record of an authorization decision."""

    __tablename__ = "decisions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        doc="Associated transaction ID if transaction was authorized.",
    )
    request_reference: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
        doc="Agent proposal request reference identifier.",
    )
    decision: Mapped[DecisionOutcome] = mapped_column(
        SQLEnum(DecisionOutcome, native_enum=False, length=32),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Deterministic justification trace for the decision.",
    )
    evidence_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Structured policy context and rule evaluation metrics.",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="decisions")
    transaction: Mapped["Transaction | None"] = relationship(
        "Transaction", back_populates="decisions"
    )

    def __repr__(self) -> str:
        return (
            f"<Decision id={self.id} user_id={self.user_id} "
            f"outcome={self.decision} reason={self.reason!r}>"
        )
