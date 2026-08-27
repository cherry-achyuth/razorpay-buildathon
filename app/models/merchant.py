"""Merchant domain model."""

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseSystemModel
from app.models.enums import MerchantStatus

if TYPE_CHECKING:
    from app.models.mandate import Mandate
    from app.models.transaction import Transaction


class Merchant(BaseSystemModel):
    """Merchant entity representing a commercial payee or platform."""

    __tablename__ = "merchants"

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    external_reference: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=True,
        doc="External merchant ID from payment gateways or agent registry.",
    )
    status: Mapped[MerchantStatus] = mapped_column(
        SQLEnum(MerchantStatus, native_enum=False, length=32),
        default=MerchantStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    # Relationships
    mandates: Mapped[list["Mandate"]] = relationship(
        "Mandate",
        back_populates="merchant",
        passive_deletes=True,
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="merchant",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Merchant id={self.id} name={self.name!r} status={self.status}>"
