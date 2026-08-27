"""API routes for Autonomous AI Buying Agent."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.agent import (
    AgentEvaluateRequest,
    AgentEvaluateResponse,
    AgentInterpretRequest,
    PaymentIntent,
)
from app.services.agent.buying_agent import BuyingAgentService

router = APIRouter(prefix="/agent", tags=["AI Buying Agent"])


@router.post(
    "/interpret",
    response_model=PaymentIntent,
    status_code=status.HTTP_200_OK,
    summary="Parse Natural Language into Structured Payment Intent",
    description=(
        "Translates a natural language purchase request into a validated, entity-resolved "
        "PaymentIntent schema without authorizing money movement."
    ),
)
async def interpret_purchase_request(
    request: AgentInterpretRequest,
    db: AsyncSession = Depends(get_db_session),
) -> PaymentIntent:
    """Extract structured intent from natural language instructions."""
    intent = await BuyingAgentService.interpret_request(
        prompt=request.prompt,
        user_id=request.user_id,
        db=db,
        currency=request.currency,
    )
    await db.commit()
    return intent


@router.post(
    "/evaluate",
    response_model=AgentEvaluateResponse,
    status_code=status.HTTP_200_OK,
    summary="Agentic Purchase Evaluation & Execution Pipeline",
    description=(
        "Executes complete autonomous pipeline: Natural Language -> Structured Intent -> "
        "DecisionVault Memory & Guardrail Evaluation -> Optional Gated Razorpay Payment."
    ),
)
async def evaluate_agent_purchase(
    request: AgentEvaluateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> AgentEvaluateResponse:
    """Evaluate and optionally execute an agentic purchase instruction."""
    result = await BuyingAgentService.evaluate_agent_purchase(
        request=request,
        db=db,
    )
    await db.commit()
    return result
