"""Tamper-Evident Hash-Chained Audit Log domain model."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AuditEventType

if TYPE_CHECKING:
    from app.models.user import User


class AuditLog(Base):
    """Tamper-evident hash-chained audit log entity.

    Records an append-oriented, cryptographically chained operational trail
    for decision evaluations and memory operations.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        index=True,
        doc="Monotonically increasing sequence index of the audit chain.",
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Associated user principal if user-scoped.",
    )
    event_type: Mapped[AuditEventType] = mapped_column(
        SQLEnum(AuditEventType, native_enum=False, length=32),
        nullable=False,
        index=True,
        doc="Categorical classification of the audited event.",
    )
    entity_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Target entity domain classification (DECISION, MEMORY, TRANSACTION).",
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        doc="Primary key UUID of the target entity if applicable.",
    )
    event_data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Deterministic structured evidence payload.",
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="Exact timestamp when the audited event occurred.",
    )
    previous_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="SHA-256 hash of the immediately preceding record (NULL for genesis).",
    )
    record_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="SHA-256 cryptographic hash of the canonicalized record content.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )

    # Relationships
    user: Mapped["User | None"] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<AuditLog seq={self.sequence_number} event={self.event_type} "
            f"entity={self.entity_type}:{self.entity_id} hash={self.record_hash[:8]}...>"
        )
