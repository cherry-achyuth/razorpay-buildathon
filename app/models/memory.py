"""Decision Memory domain models."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BaseSystemModel
from app.models.enums import (
    MemoryRelevance,
    MemorySourceType,
    MemoryStatus,
    MemoryType,
)

if TYPE_CHECKING:
    from app.models.user import User


class DecisionMemory(BaseSystemModel):
    """Derived decision-relevant memory entity.

    Decision memory preserves structured historical context, patterns, and anomalies
    derived from raw PostgreSQL financial history. Raw transactions remain the
    authoritative source of truth.
    """

    __tablename__ = "decision_memories"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="User principal who owns this decision memory.",
    )
    memory_type: Mapped[MemoryType] = mapped_column(
        SQLEnum(MemoryType, native_enum=False, length=32),
        nullable=False,
        index=True,
        doc="Domain categorization of this memory item.",
    )
    relevance: Mapped[MemoryRelevance] = mapped_column(
        SQLEnum(MemoryRelevance, native_enum=False, length=16),
        nullable=False,
        index=True,
        doc="Deterministic relevance priority (CRITICAL, HIGH, NORMAL, LOW).",
    )
    status: Mapped[MemoryStatus] = mapped_column(
        SQLEnum(MemoryStatus, native_enum=False, length=16),
        nullable=False,
        default=MemoryStatus.ACTIVE,
        index=True,
        doc="Lifecycle status (ACTIVE, SUPERSEDED, RETIRED).",
    )
    summary: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Deterministic structured summary derived from verified data.",
    )
    structured_data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Explicitly typed metrics, baseline amount, counts, or parameters.",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384),
        nullable=True,
        doc="Semantic vector embedding representing canonical memory text.",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="Memory evolution version.",
    )
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Start timestamp of memory validity window if applicable.",
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="End timestamp of memory validity window if applicable.",
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="memories",
        passive_deletes=True,
    )
    sources: Mapped[list["DecisionMemorySource"]] = relationship(
        "DecisionMemorySource",
        back_populates="memory",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<DecisionMemory id={self.id} type={self.memory_type} "
            f"relevance={self.relevance} status={self.status}>"
        )


class DecisionMemorySource(Base):
    """Source event association providing explicit provenance for a decision memory."""

    __tablename__ = "decision_memory_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("decision_memories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Parent decision memory.",
    )
    source_type: Mapped[MemorySourceType] = mapped_column(
        SQLEnum(MemorySourceType, native_enum=False, length=32),
        nullable=False,
        index=True,
        doc="Source entity type (TRANSACTION, DECISION, etc.).",
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        doc="Primary key UUID of the source entity.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "memory_id",
            "source_type",
            "source_id",
            name="uq_decision_memory_source",
        ),
    )

    memory: Mapped["DecisionMemory"] = relationship(
        "DecisionMemory",
        back_populates="sources",
    )

    def __repr__(self) -> str:
        return (
            f"<DecisionMemorySource memory_id={self.memory_id} "
            f"type={self.source_type} id={self.source_id}>"
        )
