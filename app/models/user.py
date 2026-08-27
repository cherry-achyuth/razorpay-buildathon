"""User domain model."""

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseSystemModel
from app.models.enums import UserStatus

if TYPE_CHECKING:
    from app.models.decision import Decision
    from app.models.mandate import Mandate
    from app.models.memory import DecisionMemory
    from app.models.policy import Policy
    from app.models.transaction import Transaction


class User(BaseSystemModel):
    """User account entity representing the financial authorization principal.

    Contains minimal identity metadata without storing unnecessary PII.
    """

    __tablename__ = "users"

    external_reference: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=True,
        doc="External identifier from auth provider or agent client.",
    )
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(UserStatus, native_enum=False, length=32),
        default=UserStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    # Relationships (passive_deletes=True enforces database-level RESTRICT)
    mandates: Mapped[list["Mandate"]] = relationship(
        "Mandate",
        back_populates="user",
        passive_deletes=True,
    )
    policies: Mapped[list["Policy"]] = relationship(
        "Policy",
        back_populates="user",
        passive_deletes=True,
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="user",
        passive_deletes=True,
    )
    decisions: Mapped[list["Decision"]] = relationship(
        "Decision",
        back_populates="user",
        passive_deletes=True,
    )
    memories: Mapped[list["DecisionMemory"]] = relationship(
        "DecisionMemory",
        back_populates="user",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} status={self.status}>"
