"""Pydantic schemas for Tamper-Evident Audit Log API."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AuditEventType


class AuditRecordSchema(BaseModel):
    """Schema representing an individual tamper-evident audit record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence_number: int = Field(
        description="Monotonic sequence number in the audit chain."
    )
    user_id: uuid.UUID | None = Field(
        default=None, description="User principal ID if user-scoped."
    )
    event_type: AuditEventType = Field(description="Categorical audit event type.")
    entity_type: str = Field(
        description="Target entity classification (DECISION, MEMORY, etc.)."
    )
    entity_id: uuid.UUID | None = Field(
        default=None, description="Target entity identifier."
    )
    event_data: dict[str, Any] = Field(
        default_factory=dict, description="Structured evidence payload."
    )
    occurred_at: datetime = Field(description="Event occurrence timestamp.")
    previous_hash: str | None = Field(
        default=None, description="SHA-256 hash of preceding record."
    )
    record_hash: str = Field(
        description="SHA-256 cryptographic hash of canonical record content."
    )
    created_at: datetime


class AuditListResponse(BaseModel):
    """Paginated list of audit records."""

    records: list[AuditRecordSchema]
    count: int


class AuditVerificationResponse(BaseModel):
    """Response reporting deterministic cryptographic verification of the audit chain."""

    valid: bool = Field(
        description="True if the entire hash-chain is cryptographically valid and continuous."
    )
    records_checked: int = Field(
        description="Total audit records verified in the linear sequence."
    )
    first_invalid_record_id: uuid.UUID | None = Field(
        default=None,
        description="ID of the first record where tampering or hash mismatch was detected.",
    )
    first_invalid_sequence: int | None = Field(
        default=None,
        description="Sequence number where verification failed.",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Diagnostic explanation if chain verification failed.",
    )
    expected_hash: str | None = Field(
        default=None, description="Expected SHA-256 hash."
    )
    actual_hash: str | None = Field(
        default=None, description="Stored SHA-256 hash found on record."
    )
