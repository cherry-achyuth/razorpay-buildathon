"""Decision Preservation comparative evaluation service."""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    AuditEventType,
    DecisionMismatchType,
    MemoryRelevance,
    MemoryStatus,
    ScenarioSuite,
    TransactionStatus,
)
from app.models.memory import DecisionMemory, DecisionMemorySource
from app.models.transaction import Transaction
from app.services.audit.service import AuditLogService
from app.services.evaluation.baseline import FullHistoryBaselineEvaluator
from app.services.evaluation.compressed import CompressedMemoryEvaluator
from app.services.evaluation.metrics import (
    EvaluationAggregateResult,
    EvaluationScenarioResult,
    calculate_compression_metrics,
    calculate_critical_memory_recall,
    classify_decision_mismatch,
)
from app.services.evaluation.scenarios import (
    EvaluationScenarioDefinition,
    ScenarioFactory,
)
from app.services.guardrails.base import DecisionMemoryContext

logger = logging.getLogger(__name__)


class DecisionPreservationService:
    """Orchestrates comparative evaluation between Full History and Compressed Decision Memory."""

    def __init__(
        self,
        baseline_evaluator: FullHistoryBaselineEvaluator | None = None,
        compressed_evaluator: CompressedMemoryEvaluator | None = None,
    ) -> None:
        self.baseline_evaluator = baseline_evaluator or FullHistoryBaselineEvaluator()
        self.compressed_evaluator = compressed_evaluator or CompressedMemoryEvaluator()

    async def run_evaluation(
        self,
        user_id: uuid.UUID,
        db: AsyncSession,
        scenarios: list[EvaluationScenarioDefinition] | None = None,
        suite: ScenarioSuite = ScenarioSuite.STANDARD,
        as_of: datetime | None = None,
        custom_memory_contexts: Sequence[DecisionMemoryContext] | None = None,
        record_audit: bool = True,
    ) -> EvaluationAggregateResult:
        """Execute full comparative evaluation across scenarios."""
        experiment_id = uuid.uuid4()
        now = as_of or datetime.now(UTC)
        suite_name = suite.value if isinstance(suite, ScenarioSuite) else str(suite)

        # 1. Resolve or Generate Scenarios
        eval_scenarios = scenarios or []
        if not eval_scenarios:
            # Look up known merchants for the user to construct benchmark scenarios
            m_id_stmt = (
                select(Transaction.merchant_id)
                .where(Transaction.user_id == user_id)
                .distinct()
                .limit(2)
            )
            found_m_ids = list((await db.scalars(m_id_stmt)).all())
            routine_m_id = found_m_ids[0] if len(found_m_ids) > 0 else uuid.uuid4()
            secondary_m_id = found_m_ids[1] if len(found_m_ids) > 1 else uuid.uuid4()
            unfamiliar_m_id = uuid.uuid4()
            similar_m_id = uuid.uuid4()

            if suite == ScenarioSuite.ADVERSARIAL:
                eval_scenarios = ScenarioFactory.create_adversarial_scenarios(
                    user_id=user_id,
                    routine_merchant_id=routine_m_id,
                    unfamiliar_merchant_id=unfamiliar_m_id,
                    secondary_known_merchant_id=secondary_m_id,
                    similar_name_merchant_id=similar_m_id,
                )
            else:
                eval_scenarios = ScenarioFactory.create_standard_scenarios(
                    user_id=user_id,
                    routine_merchant_id=routine_m_id,
                    unfamiliar_merchant_id=unfamiliar_m_id,
                )
        else:
            suite_name = ScenarioSuite.CUSTOM.value

        scenario_results: list[EvaluationScenarioResult] = []
        matching_count = 0
        mismatch_count = 0
        safety_critical_cases = 0
        safety_critical_matches = 0
        false_allow_count = 0
        false_block_count = 0
        false_ask_user_count = 0
        missed_block_count = 0
        missed_ask_user_count = 0

        # 2. Run Comparative Evaluation for Each Scenario
        for sc in eval_scenarios:
            full_res = await self.baseline_evaluator.evaluate_scenario(
                scenario=sc, db=db, as_of=now
            )
            comp_res = await self.compressed_evaluator.evaluate_scenario(
                scenario=sc,
                db=db,
                as_of=now,
                custom_memory_contexts=custom_memory_contexts,
            )

            is_match = full_res.decision == comp_res.decision
            mismatch_type, is_safety_crit = classify_decision_mismatch(
                full_history_decision=full_res.decision,
                compressed_memory_decision=comp_res.decision,
            )

            if is_match:
                matching_count += 1
            else:
                mismatch_count += 1

            # Tally mismatch types
            if mismatch_type == DecisionMismatchType.FALSE_ALLOW:
                false_allow_count += 1
            elif mismatch_type == DecisionMismatchType.FALSE_BLOCK:
                false_block_count += 1
            elif mismatch_type == DecisionMismatchType.FALSE_ASK_USER:
                false_ask_user_count += 1
            elif mismatch_type == DecisionMismatchType.MISSED_BLOCK:
                missed_block_count += 1
            elif mismatch_type == DecisionMismatchType.MISSED_ASK_USER:
                missed_ask_user_count += 1

            # Safety-critical preservation metrics
            # A case is safety-critical if full history demanded BLOCK or ASK_USER
            if full_res.decision in {
                full_res.decision.BLOCK,
                full_res.decision.ASK_USER,
            }:
                safety_critical_cases += 1
                if is_match:
                    safety_critical_matches += 1

            scenario_results.append(
                EvaluationScenarioResult(
                    scenario_id=sc.scenario_id,
                    name=sc.name,
                    full_history_decision=full_res.decision,
                    full_history_reason_code=full_res.reason_code,
                    compressed_memory_decision=comp_res.decision,
                    compressed_memory_reason_code=comp_res.reason_code,
                    decision_match=is_match,
                    mismatch_type=mismatch_type,
                    safety_critical=is_safety_crit,
                    category=getattr(sc, "category", "GENERAL"),
                    details={
                        "amount": str(sc.amount),
                        "currency": sc.currency,
                        "merchant_id": str(sc.merchant_id),
                        "full_history_reason": full_res.reason,
                        "compressed_memory_reason": comp_res.reason,
                    },
                )
            )

        # 3. Calculate Decision Preservation Rates
        total_scenarios = len(eval_scenarios)
        preservation_rate = (
            round(float(matching_count) / float(total_scenarios), 4)
            if total_scenarios > 0
            else 1.0
        )

        safety_rate = (
            round(
                float(safety_critical_matches) / float(safety_critical_cases),
                4,
            )
            if safety_critical_cases > 0
            else 1.0
        )

        # 4. Resolve Actual Compression Statistics from Database
        src_count_stmt = select(func.count(Transaction.id)).where(
            Transaction.user_id == user_id
        )
        source_count = await db.scalar(src_count_stmt) or 0

        mem_count_stmt = select(func.count(DecisionMemory.id)).where(
            DecisionMemory.user_id == user_id,
            DecisionMemory.status == MemoryStatus.ACTIVE,
        )
        retained_mem_count = await db.scalar(mem_count_stmt) or 0

        compression_ratio, compression_pct = calculate_compression_metrics(
            source_event_count=source_count,
            retained_memory_count=retained_mem_count,
        )

        # 5. Calculate Critical-Memory Recall
        crit_tx_stmt = select(Transaction.id).where(
            Transaction.user_id == user_id,
            Transaction.status.in_(
                [TransactionStatus.FAILED, TransactionStatus.CANCELLED]
            ),
        )
        crit_tx_ids = set((await db.scalars(crit_tx_stmt)).all())

        if crit_tx_ids:
            preserved_stmt = (
                select(DecisionMemorySource.source_id)
                .join(
                    DecisionMemory,
                    DecisionMemory.id == DecisionMemorySource.memory_id,
                )
                .where(
                    DecisionMemory.user_id == user_id,
                    DecisionMemory.status == MemoryStatus.ACTIVE,
                    DecisionMemory.relevance.in_(
                        [MemoryRelevance.CRITICAL, MemoryRelevance.HIGH]
                    ),
                    DecisionMemorySource.source_id.in_(crit_tx_ids),
                )
            )
            preserved_ids = set((await db.scalars(preserved_stmt)).all())
            crit_recall = calculate_critical_memory_recall(
                critical_events_required=len(crit_tx_ids),
                critical_events_preserved=len(preserved_ids),
            )
        else:
            # When no critical failed transactions exist, check active critical memory items
            crit_mem_stmt = select(func.count(DecisionMemory.id)).where(
                DecisionMemory.user_id == user_id,
                DecisionMemory.status == MemoryStatus.ACTIVE,
                DecisionMemory.relevance.in_(
                    [MemoryRelevance.CRITICAL, MemoryRelevance.HIGH]
                ),
            )
            crit_mem_count = await db.scalar(crit_mem_stmt) or 0
            crit_recall = calculate_critical_memory_recall(
                critical_events_required=crit_mem_count,
                critical_events_preserved=crit_mem_count,
            )

        aggregate_result = EvaluationAggregateResult(
            experiment_id=experiment_id,
            user_id=user_id,
            total_scenarios=total_scenarios,
            matching_decisions=matching_count,
            mismatching_decisions=mismatch_count,
            decision_preservation_rate=preservation_rate,
            safety_critical_cases=safety_critical_cases,
            safety_critical_matches=safety_critical_matches,
            safety_critical_preservation_rate=safety_rate,
            false_allow_count=false_allow_count,
            false_block_count=false_block_count,
            false_ask_user_count=false_ask_user_count,
            missed_block_count=missed_block_count,
            missed_ask_user_count=missed_ask_user_count,
            source_event_count=source_count,
            retained_memory_count=retained_mem_count,
            compression_ratio=compression_ratio,
            compression_percentage=compression_pct,
            scenario_suite=suite_name,
            critical_memory_recall=crit_recall,
            scenarios=scenario_results,
            evaluated_at=now,
        )

        # 6. Append Tamper-Evident Audit Event if enabled
        if record_audit:
            try:
                await AuditLogService.append_event(
                    db=db,
                    event_type=AuditEventType.DECISION_PRESERVATION_EVALUATED,
                    entity_type="EVALUATION_EXPERIMENT",
                    entity_id=experiment_id,
                    user_id=user_id,
                    event_data={
                        "experiment_id": str(experiment_id),
                        "scenario_suite": suite_name,
                        "total_scenarios": total_scenarios,
                        "matching_decisions": matching_count,
                        "mismatching_decisions": mismatch_count,
                        "decision_preservation_rate": preservation_rate,
                        "safety_critical_preservation_rate": safety_rate,
                        "critical_memory_recall": crit_recall,
                        "false_allow_count": false_allow_count,
                        "false_block_count": false_block_count,
                        "missed_block_count": missed_block_count,
                        "compression_ratio": compression_ratio,
                    },
                    occurred_at=now,
                )
                await db.commit()
            except Exception as exc:
                logger.error(
                    "Failed to record audit event for evaluation experiment %s: %s",
                    experiment_id,
                    exc,
                )

        return aggregate_result
