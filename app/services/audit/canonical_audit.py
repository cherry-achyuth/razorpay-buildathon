"""Deterministic canonical serialization and cryptographic hashing for Audit Logs."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


def _json_serial_default(obj: Any) -> Any:
    """Deterministic JSON serializer for non-standard types."""
    if isinstance(obj, uuid.UUID):
        return str(obj).lower()
    if isinstance(obj, datetime):
        utc_dt = obj if obj.tzinfo else obj.replace(tzinfo=UTC)
        return utc_dt.astimezone(UTC).isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def canonical_json(data: dict[str, Any]) -> str:
    """Serialize a dictionary to a stable, deterministic JSON string with sorted keys."""
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_serial_default,
        ensure_ascii=True,
    )


def canonical_audit_string(
    sequence_number: int,
    previous_hash: str | None,
    user_id: uuid.UUID | str | None,
    event_type: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None,
    event_data: dict[str, Any],
    occurred_at: datetime,
) -> str:
    """Construct deterministic canonical string representation of an audit record.

    Ensures that any alteration in sequence, linkage, timestamps, identifiers,
    or structured payload changes the resulting canonical string and SHA-256 hash.
    """
    uid_str = str(user_id).lower() if user_id else ""
    eid_str = str(entity_id).lower() if entity_id else ""
    prev_hash_str = previous_hash if previous_hash is not None else ""

    utc_dt = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
    occ_str = utc_dt.astimezone(UTC).isoformat()
    canonical_data = canonical_json(event_data)

    return (
        f"seq:{sequence_number}|"
        f"prev:{prev_hash_str}|"
        f"user:{uid_str}|"
        f"type:{event_type}|"
        f"entity:{entity_type}:{eid_str}|"
        f"time:{occ_str}|"
        f"data:{canonical_data}"
    )


def calculate_record_hash(canonical_str: str) -> str:
    """Compute SHA-256 hex digest for canonical audit string."""
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
