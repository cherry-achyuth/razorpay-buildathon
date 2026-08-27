"""Baseline foundation model definitions."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseSystemModel


class SystemMetadata(BaseSystemModel):
    """System metadata and audit foundation model.

    Demonstrates and validates ORM architecture, UUID primary keys,
    timezone-aware timestamps, and schema migrations.
    """

    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
    )
    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<SystemMetadata key={self.key!r}>"
