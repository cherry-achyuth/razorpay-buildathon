"""Decision Preservation Evaluation API endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.evaluation import (
    EvaluationRequest,
    EvaluationResponse,
    EvaluationScenarioResultSchema,
)
from app.services.evaluation.decision_preservation import DecisionPreservationService
from app.services.evaluation.scenarios import EvaluationScenarioDefinition

router = APIRouter(prefix="/evaluations", tags=["Decision-Preservation Evaluation"])


@router.post(
    "/decision-preservation",
    response_model=EvaluationResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate Decision Preservation: Full History vs Compressed Memory",
    description=(
        "Executes a deterministic comparative evaluation comparing decisions derived "
        "from full raw historical transactions against decisions derived from compressed "
        "DecisionMemory context, detecting and classifying any decision differences."
    ),
)
async def evaluate_decision_preservation(
    payload: EvaluationRequest,
    db: AsyncSession = Depends(get_db_session),
) -> EvaluationResponse:
    """Run decision-preservation evaluation for a user."""
    custom_scenarios: list[EvaluationScenarioDefinition] | None = None
    if payload.scenarios:
        custom_scenarios = [
            EvaluationScenarioDefinition(
                scenario_id=s.scenario_id,
                name=s.name,
                user_id=payload.user_id,
                merchant_id=s.merchant_id,
                amount=s.amount,
                currency=s.currency,
                mandate_id=s.mandate_id,
                transaction_type=s.transaction_type,
                category=s.category,
                description=s.description,
            )
            for s in payload.scenarios
        ]

    eval_service = DecisionPreservationService()
    result = await eval_service.run_evaluation(
        user_id=payload.user_id,
        db=db,
        scenarios=custom_scenarios,
        suite=payload.scenario_suite,
        record_audit=True,
    )

    return EvaluationResponse(
        experiment_id=result.experiment_id,
        user_id=result.user_id,
        total_scenarios=result.total_scenarios,
        matching_decisions=result.matching_decisions,
        mismatching_decisions=result.mismatching_decisions,
        decision_preservation_rate=result.decision_preservation_rate,
        safety_critical_cases=result.safety_critical_cases,
        safety_critical_matches=result.safety_critical_matches,
        safety_critical_preservation_rate=result.safety_critical_preservation_rate,
        false_allow_count=result.false_allow_count,
        false_block_count=result.false_block_count,
        false_ask_user_count=result.false_ask_user_count,
        missed_block_count=result.missed_block_count,
        missed_ask_user_count=result.missed_ask_user_count,
        source_event_count=result.source_event_count,
        retained_memory_count=result.retained_memory_count,
        compression_ratio=result.compression_ratio,
        compression_percentage=result.compression_percentage,
        scenario_suite=result.scenario_suite,
        critical_memory_recall=result.critical_memory_recall,
        scenarios=[
            EvaluationScenarioResultSchema(
                scenario_id=sr.scenario_id,
                name=sr.name,
                full_history_decision=sr.full_history_decision,
                full_history_reason_code=sr.full_history_reason_code,
                compressed_memory_decision=sr.compressed_memory_decision,
                compressed_memory_reason_code=sr.compressed_memory_reason_code,
                decision_match=sr.decision_match,
                mismatch_type=sr.mismatch_type,
                safety_critical=sr.safety_critical,
                category=sr.category,
                details=sr.details,
            )
            for sr in result.scenarios
        ],
        evaluated_at=result.evaluated_at,
    )
