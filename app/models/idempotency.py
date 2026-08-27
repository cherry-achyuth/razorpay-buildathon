"""Idempotency record domain model for evaluation and payment requests."""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseSystemModel

if TYPE_CHECKING:
    from app.models.user import User


class IdempotencyRecord(BaseSystemModel):
    """Authoritative record storing request fingerprints and cached evaluation states.

    Guarantees that repeated evaluation/authorization requests with the same
    idempotency key produce deterministic responses and prevents tampering.
    """

    __tablename__ = "idempotency_records"

    key: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
        doc="Client-provided unique idempotency key.",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="User executing the idempotent action.",
    )
    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="SHA-256 fingerprint of the canonical request payload.",
    )
    response_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        doc="Cached deterministic response payload returned on matching retries.",
    )

    # Relationships
    user: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<IdempotencyRecord id={self.id} key={self.key!r} user_id={self.user_id}>"
        )
