"""Payment execution and decision confirmation API endpoints."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db_session
from app.schemas.payment import (
    DecisionConfirmationRequest,
    DecisionConfirmationResponse,
    PaymentExecutionRequest,
    PaymentExecutionResponse,
)
from app.services.payment.service import PaymentExecutionService

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "/execute",
    response_model=PaymentExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate and Execute Payment via Razorpay Test Mode",
)
async def execute_payment(
    payload: PaymentExecutionRequest,
    db: AsyncSession = Depends(get_db_session),
) -> PaymentExecutionResponse:
    """Evaluates the proposed payment through deterministic guardrails and financial memory.

    - If ALLOW: Executes payment via Razorpay Test Mode and persists transaction.
    - If ASK_USER: Halts execution and returns status REQUIRES_USER_CONFIRMATION.
    - If BLOCK: Blocks execution with zero money movement and returns safety violation reason.
    """
    service = PaymentExecutionService()
    return await service.execute_payment(payload, db)


@router.post(
    "/decisions/{decision_id}/confirm",
    response_model=DecisionConfirmationResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm an ASK_USER Decision",
)
async def confirm_decision(
    decision_id: uuid.UUID,
    payload: DecisionConfirmationRequest,
    db: AsyncSession = Depends(get_db_session),
) -> DecisionConfirmationResponse:
    """Explicitly authorizes or rejects a pending ASK_USER decision."""
    service = PaymentExecutionService()
    return await service.confirm_decision(decision_id, payload, db)


@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    summary="Get Razorpay Gateway Configuration Status",
)
async def get_payment_gateway_status() -> dict[str, str | bool]:
    """Returns gateway configuration status without leaking secret credentials."""
    settings = get_settings()
    configured = bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)
    return {
        "gateway": "Razorpay Test Mode / Sandbox",
        "configured": configured,
        "mode": "RAZORPAY_TEST_MODE" if configured else "SANDBOX_SIMULATION",
        "key_id_preview": (
            f"{settings.RAZORPAY_KEY_ID[:8]}..."
            if settings.RAZORPAY_KEY_ID
            else "NOT_CONFIGURED"
        ),
        "currency_default": settings.RAZORPAY_CURRENCY_DEFAULT,
    }
