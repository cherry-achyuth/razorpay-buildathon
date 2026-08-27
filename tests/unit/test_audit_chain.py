"""Unit tests for deterministic canonical audit serialization and hash chaining."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models.enums import AuditEventType
from app.services.audit.canonical_audit import (
    calculate_record_hash,
    canonical_audit_string,
    canonical_json,
)


def test_canonical_json_deterministic_key_ordering():
    """Verify that dictionaries with different insertion orders serialize to identical strings."""
    d1 = {"currency": "USD", "amount": "25.00", "user_id": "123"}
    d2 = {"user_id": "123", "currency": "USD", "amount": "25.00"}
    assert canonical_json(d1) == canonical_json(d2)
    assert canonical_json(d1) == '{"amount":"25.00","currency":"USD","user_id":"123"}'


def test_canonical_json_handles_uuid_datetime_decimal():
    """Verify that UUIDs, datetimes, and Decimals serialize deterministically."""
    uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    dt = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
    dec = Decimal("150.5000")

    payload = {"id": uid, "time": dt, "amount": dec}
    serialized = canonical_json(payload)
    assert '"id":"12345678-1234-5678-1234-567812345678"' in serialized
    assert '"time":"2026-08-23T12:00:00+00:00"' in serialized
    assert '"amount":"150.5000"' in serialized


def test_canonical_audit_string_reproducibility():
    """Verify canonical string is 100% reproducible for identical inputs."""
    uid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    eid = uuid.UUID("22222222-2222-2222-2222-222222222222")
    now = datetime(2026, 8, 23, 15, 30, 0, tzinfo=UTC)
    data = {"metric": "value", "count": 5}

    s1 = canonical_audit_string(
        sequence_number=1,
        previous_hash=None,
        user_id=uid,
        event_type="MEMORY_CREATED",
        entity_type="MEMORY",
        entity_id=eid,
        event_data=data,
        occurred_at=now,
    )
    s2 = canonical_audit_string(
        sequence_number=1,
        previous_hash=None,
        user_id=uid,
        event_type="MEMORY_CREATED",
        entity_type="MEMORY",
        entity_id=eid,
        event_data=data,
        occurred_at=now,
    )
    assert s1 == s2
    assert calculate_record_hash(s1) == calculate_record_hash(s2)


def test_canonical_audit_string_sensitivity_to_modifications():
    """Verify modifying any field changes the canonical string and SHA-256 hash."""
    uid = uuid.uuid4()
    eid = uuid.uuid4()
    now = datetime(2026, 8, 23, 10, 0, 0, tzinfo=UTC)
    base_data = {"key": "val"}

    base_str = canonical_audit_string(
        sequence_number=2,
        previous_hash="0000aaaa1111bbbb",
        user_id=uid,
        event_type=AuditEventType.DECISION_EVALUATED.value,
        entity_type="DECISION",
        entity_id=eid,
        event_data=base_data,
        occurred_at=now,
    )
    base_hash = calculate_record_hash(base_str)

    # 1. Alter sequence number
    alt_seq = canonical_audit_string(
        sequence_number=3,
        previous_hash="0000aaaa1111bbbb",
        user_id=uid,
        event_type=AuditEventType.DECISION_EVALUATED.value,
        entity_type="DECISION",
        entity_id=eid,
        event_data=base_data,
        occurred_at=now,
    )
    assert calculate_record_hash(alt_seq) != base_hash

    # 2. Alter previous hash
    alt_prev = canonical_audit_string(
        sequence_number=2,
        previous_hash="different_hash_value",
        user_id=uid,
        event_type=AuditEventType.DECISION_EVALUATED.value,
        entity_type="DECISION",
        entity_id=eid,
        event_data=base_data,
        occurred_at=now,
    )
    assert calculate_record_hash(alt_prev) != base_hash

    # 3. Alter event type
    alt_type = canonical_audit_string(
        sequence_number=2,
        previous_hash="0000aaaa1111bbbb",
        user_id=uid,
        event_type=AuditEventType.MEMORY_COMPRESSED.value,
        entity_type="DECISION",
        entity_id=eid,
        event_data=base_data,
        occurred_at=now,
    )
    assert calculate_record_hash(alt_type) != base_hash

    # 4. Alter payload data
    alt_data = canonical_audit_string(
        sequence_number=2,
        previous_hash="0000aaaa1111bbbb",
        user_id=uid,
        event_type=AuditEventType.DECISION_EVALUATED.value,
        entity_type="DECISION",
        entity_id=eid,
        event_data={"key": "tampered_val"},
        occurred_at=now,
    )
    assert calculate_record_hash(alt_data) != base_hash
