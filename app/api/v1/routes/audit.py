"""Audit Log API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.audit import (
    AuditListResponse,
    AuditRecordSchema,
    AuditVerificationResponse,
)
from app.services.audit.service import AuditLogService

router = APIRouter(prefix="/audit", tags=["Audit Log"])


@router.get(
    "/verify",
    response_model=AuditVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify Tamper-Evident Audit Chain Integrity",
    description=(
        "Performs complete deterministic cryptographic verification of the audit log "
        "hash-chain, checking sequence continuity, previous-hash linkage, and record hashes."
    ),
)
async def verify_audit_chain(
    db: AsyncSession = Depends(get_db_session),
) -> AuditVerificationResponse:
    """Verify cryptographic integrity of the linear audit log chain."""
    result = await AuditLogService.verify_chain(db=db)
    return AuditVerificationResponse(
        valid=result.valid,
        records_checked=result.records_checked,
        first_invalid_record_id=result.first_invalid_record_id,
        first_invalid_sequence=result.first_invalid_sequence,
        failure_reason=result.failure_reason,
        expected_hash=result.expected_hash,
        actual_hash=result.actual_hash,
    )


@router.get(
    "",
    response_model=AuditListResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve Audit Records",
    description="Retrieves audit records in reverse sequence order, optionally scoped to a user.",
)
async def get_audit_logs(
    user_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional user ID principal for tenant filtering."),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Maximum records to return.")
    ] = 50,
    offset: Annotated[int, Query(ge=0, description="Pagination offset.")] = 0,
    db: AsyncSession = Depends(get_db_session),
) -> AuditListResponse:
    """Retrieve audit records."""
    records = await AuditLogService.get_audit_logs(
        db=db,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    validated = [AuditRecordSchema.model_validate(r) for r in records]
    return AuditListResponse(records=validated, count=len(validated))
