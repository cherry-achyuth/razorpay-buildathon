"""Tamper-Evident Hash-Chained Audit Log Service."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.enums import AuditEventType
from app.services.audit.canonical_audit import (
    calculate_record_hash,
    canonical_audit_string,
)

logger = logging.getLogger(__name__)


@dataclass
class AuditVerificationResult:
    """Detailed cryptographic verification result of the audit log chain."""

    valid: bool
    records_checked: int
    first_invalid_record_id: uuid.UUID | None = None
    first_invalid_sequence: int | None = None
    failure_reason: str | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None


class AuditLogService:
    """Service managing append-oriented, tamper-evident hash-chained audit trails.

    Guarantees:
    1. Append-only operational logging.
    2. Monotonic sequence numbering and cryptographic SHA-256 hash chaining.
    3. Detectability of payload alterations, deletions, reorderings, and link tampering.
    4. Observational only: audit logging NEVER possesses financial authorization power.
    """

    @classmethod
    async def append_event(
        cls,
        db: AsyncSession,
        event_type: AuditEventType,
        entity_type: str,
        entity_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        event_data: dict | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditLog:
        """Append a new tamper-evident audit record to the linear chain."""
        # 1. Resolve latest record in chain to establish next sequence and previous_hash
        bind = db.bind
        dialect_name = bind.dialect.name if bind else "postgresql"

        stmt = select(AuditLog).order_by(AuditLog.sequence_number.desc()).limit(1)
        if dialect_name == "postgresql":
            stmt = stmt.with_for_update()

        latest = await db.scalar(stmt)

        next_sequence = (latest.sequence_number + 1) if latest else 1
        prev_hash = latest.record_hash if latest else None
        effective_occurred = occurred_at or datetime.now(UTC)
        payload_data = dict(event_data or {})

        # 2. Construct canonical string and compute SHA-256 record hash
        canonical_str = canonical_audit_string(
            sequence_number=next_sequence,
            previous_hash=prev_hash,
            user_id=user_id,
            event_type=event_type.value
            if hasattr(event_type, "value")
            else str(event_type),
            entity_type=entity_type,
            entity_id=entity_id,
            event_data=payload_data,
            occurred_at=effective_occurred,
        )
        rec_hash = calculate_record_hash(canonical_str)

        # 3. Create AuditLog record and flush within caller's transaction
        audit_record = AuditLog(
            id=uuid.uuid4(),
            sequence_number=next_sequence,
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            event_data=payload_data,
            occurred_at=effective_occurred,
            previous_hash=prev_hash,
            record_hash=rec_hash,
        )
        db.add(audit_record)
        await db.flush()

        logger.debug(
            "Appended audit record seq=%s event=%s entity=%s:%s hash=%s",
            next_sequence,
            event_type,
            entity_type,
            entity_id,
            rec_hash[:12],
        )
        return audit_record

    @classmethod
    async def verify_chain(
        cls,
        db: AsyncSession,
    ) -> AuditVerificationResult:
        """Deterministically verify the unbroken cryptographic integrity of the audit chain."""
        stmt = select(AuditLog).order_by(AuditLog.sequence_number.asc())
        result = await db.scalars(stmt)
        records = list(result.all())

        if not records:
            return AuditVerificationResult(
                valid=True,
                records_checked=0,
            )

        expected_sequence = 1
        prev_record: AuditLog | None = None

        for idx, rec in enumerate(records):
            # Check 1: Sequence Number Continuity
            if rec.sequence_number != expected_sequence:
                return AuditVerificationResult(
                    valid=False,
                    records_checked=idx,
                    first_invalid_record_id=rec.id,
                    first_invalid_sequence=rec.sequence_number,
                    failure_reason=f"SEQUENCE_GAP_OR_MISMATCH: expected {expected_sequence}, found {rec.sequence_number}",
                )

            # Check 2: Previous Hash Linkage
            if idx == 0:
                if rec.previous_hash is not None:
                    return AuditVerificationResult(
                        valid=False,
                        records_checked=idx,
                        first_invalid_record_id=rec.id,
                        first_invalid_sequence=rec.sequence_number,
                        failure_reason="GENESIS_RECORD_PREVIOUS_HASH_NOT_NULL",
                        expected_hash=None,
                        actual_hash=rec.previous_hash,
                    )
            else:
                assert prev_record is not None
                if rec.previous_hash != prev_record.record_hash:
                    return AuditVerificationResult(
                        valid=False,
                        records_checked=idx,
                        first_invalid_record_id=rec.id,
                        first_invalid_sequence=rec.sequence_number,
                        failure_reason="PREVIOUS_HASH_LINKAGE_MISMATCH",
                        expected_hash=prev_record.record_hash,
                        actual_hash=rec.previous_hash,
                    )

            # Check 3: Cryptographic Hash Reproduction from Canonical Fields
            canonical_str = canonical_audit_string(
                sequence_number=rec.sequence_number,
                previous_hash=rec.previous_hash,
                user_id=rec.user_id,
                event_type=rec.event_type.value
                if hasattr(rec.event_type, "value")
                else str(rec.event_type),
                entity_type=rec.entity_type,
                entity_id=rec.entity_id,
                event_data=rec.event_data,
                occurred_at=rec.occurred_at,
            )
            recomputed_hash = calculate_record_hash(canonical_str)

            if recomputed_hash != rec.record_hash:
                return AuditVerificationResult(
                    valid=False,
                    records_checked=idx,
                    first_invalid_record_id=rec.id,
                    first_invalid_sequence=rec.sequence_number,
                    failure_reason="RECORD_HASH_MISMATCH",
                    expected_hash=recomputed_hash,
                    actual_hash=rec.record_hash,
                )

            expected_sequence += 1
            prev_record = rec

        return AuditVerificationResult(
            valid=True,
            records_checked=len(records),
        )

    @classmethod
    async def get_audit_logs(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]:
        """Retrieve audit records in reverse chronological sequence, optionally scoped to a user."""
        safe_limit = max(1, min(limit, 100))
        stmt = select(AuditLog)
        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        stmt = (
            stmt.order_by(AuditLog.sequence_number.desc())
            .offset(offset)
            .limit(safe_limit)
        )
        result = await db.scalars(stmt)
        return list(result.all())

    @classmethod
    async def get_user_audit_logs(
        cls,
        user_id: uuid.UUID,
        db: AsyncSession,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]:
        """Retrieve user-scoped audit records in reverse chronological sequence."""
        return await cls.get_audit_logs(
            db=db, user_id=user_id, limit=limit, offset=offset
        )
