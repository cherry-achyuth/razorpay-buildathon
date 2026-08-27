"""Decision audit recording and deterministic policy evaluation API endpoints."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException, ResourceNotFoundError
from app.db.session import get_db_session
from app.models.decision import Decision
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.decision import (
    ActionEvaluationRequest,
    ActionEvaluationResponse,
    DecisionCreate,
    DecisionRead,
)
from app.services.decision_service import DecisionEvaluationService

router = APIRouter(prefix="/decisions", tags=["Decisions"])


@router.post(
    "/evaluate",
    response_model=ActionEvaluationResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate a Proposed Financial Action",
)
async def evaluate_decision(
    payload: ActionEvaluationRequest,
    db: AsyncSession = Depends(get_db_session),
) -> ActionEvaluationResponse:
    """Evaluates a proposed financial action against deterministic guardrails.

    CRITICAL FINTECH INVARIANTS:
    - This endpoint DOES NOT execute payments or move funds.
    - This endpoint DOES NOT create an actual transaction.
    - Evaluates against authoritative PostgreSQL state (Users, Mandates, Policies).
    - Enforces absolute BLOCK precedence.
    """
    service = DecisionEvaluationService()
    return await service.evaluate_action(payload, db)


@router.post(
    "",
    response_model=DecisionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record an Authorization Decision Outcome",
)
async def create_decision(
    payload: DecisionCreate,
    db: AsyncSession = Depends(get_db_session),
) -> Decision:
    """Stores the evaluated outcome of an authorization decision for auditability."""
    # 1. Verify User exists
    user = await db.get(User, payload.user_id)
    if not user:
        raise AppException(
            message=f"User with ID {payload.user_id} does not exist",
            error_code="USER_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 2. Verify Transaction exists if supplied
    if payload.transaction_id:
        transaction = await db.get(Transaction, payload.transaction_id)
        if not transaction:
            raise AppException(
                message=f"Transaction with ID {payload.transaction_id} does not exist",
                error_code="TRANSACTION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    decision = Decision(
        user_id=payload.user_id,
        transaction_id=payload.transaction_id,
        request_reference=payload.request_reference,
        decision=payload.decision,
        reason=payload.reason,
        evidence_metadata=payload.evidence_metadata,
    )
    db.add(decision)
    await db.flush()
    await db.refresh(decision)
    return decision


@router.get(
    "/{decision_id}",
    response_model=DecisionRead,
    status_code=status.HTTP_200_OK,
    summary="Get Decision by ID",
)
async def get_decision(
    decision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Decision:
    """Retrieves decision audit record by UUID."""
    decision = await db.get(Decision, decision_id)
    if not decision:
        raise ResourceNotFoundError(f"Decision with ID {decision_id} was not found")
    return decision
