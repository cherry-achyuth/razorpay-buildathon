"""Compressed-memory deterministic evaluator."""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ResourceNotFoundError
from app.models.enums import MemoryStatus, PolicyStatus
from app.models.mandate import Mandate
from app.models.merchant import Merchant
from app.models.policy import Policy
from app.models.user import User
from app.services.evaluation.scenarios import EvaluationScenarioDefinition
from app.services.guardrails.base import (
    DecisionMemoryContext,
    EvaluationContext,
    ProposedFinancialAction,
)
from app.services.guardrails.engine import (
    DeterministicRuleEngine,
    EngineEvaluationResult,
)
from app.services.memory.retrieval import MemoryRetrievalService

logger = logging.getLogger(__name__)


class CompressedMemoryEvaluator:
    """Evaluates financial decisions based strictly on derived DecisionMemory context.

    Rules and Invariants:
    1. Evaluates using active DecisionMemory entities loaded for the user.
    2. Does NOT have direct access to raw uncompressed historical transactions.
    3. Memory provides context to the exact same deterministic financial guardrails.
    4. Memory CANNOT independently grant authorization or bypass hard controls.
    """

    def __init__(self, engine: DeterministicRuleEngine | None = None) -> None:
        self.engine = engine or DeterministicRuleEngine()
        self.settings = get_settings()

    async def evaluate_scenario(
        self,
        scenario: EvaluationScenarioDefinition,
        db: AsyncSession,
        as_of: datetime | None = None,
        custom_memory_contexts: Sequence[DecisionMemoryContext] | None = None,
    ) -> EngineEvaluationResult:
        """Run deterministic decision evaluation using compressed DecisionMemory context."""
        now = as_of or datetime.now(UTC)

        # 1. Resolve User
        user = await db.scalar(select(User).where(User.id == scenario.user_id))
        if not user:
            raise ResourceNotFoundError(f"User with ID '{scenario.user_id}' not found.")

        # 2. Resolve Merchant
        merchant = await db.scalar(
            select(Merchant).where(Merchant.id == scenario.merchant_id)
        )
        if not merchant:
            merchant = Merchant(
                id=scenario.merchant_id,
                name="Unfamiliar Merchant",
                external_reference=f"unfam_{scenario.merchant_id}",
            )

        # 3. Resolve Mandate if specified
        mandate: Mandate | None = None
        if scenario.mandate_id:
            mandate = await db.scalar(
                select(Mandate).where(Mandate.id == scenario.mandate_id)
            )

        # 4. Resolve Active Policies
        policies_query = select(Policy).where(
            Policy.user_id == scenario.user_id,
            Policy.status == PolicyStatus.ACTIVE,
        )
        policies_res = await db.execute(policies_query)
        active_policies = list(policies_res.scalars().all())

        # 5. Resolve Memory Context (from custom list or database)
        memory_contexts: list[DecisionMemoryContext] = []
        if custom_memory_contexts is not None:
            memory_contexts = list(custom_memory_contexts)
        else:
            try:
                active_memories = await MemoryRetrievalService.get_user_memories(
                    user_id=scenario.user_id,
                    db=db,
                    status=MemoryStatus.ACTIVE,
                    as_of=now,
                    limit=self.settings.MEMORY_CONTEXT_LIMIT,
                )
                memory_contexts = [
                    DecisionMemoryContext.from_model(m) for m in active_memories
                ]
            except Exception as exc:
                logger.error(
                    "Memory retrieval failed during compressed evaluation for user %s: %s",
                    scenario.user_id,
                    exc,
                )
                memory_contexts = []

        # 6. Build Compressed Memory Evaluation Context (raw transactions are omitted)
        context = EvaluationContext(
            user=user,
            merchant=merchant,
            mandate=mandate,
            active_policies=active_policies,
            recent_window_transactions=[],  # Omitted in compressed memory evaluation
            merchant_historical_transactions=[],  # Omitted in compressed memory evaluation
            user_historical_merchant_ids=set(),  # Derived from memory_context
            user_total_historical_tx_count=0,  # Derived from memory_context
            existing_idempotency_record=None,
            duplicate_window_seconds=self.settings.DUPLICATE_DETECTION_WINDOW_SECONDS,
            price_drift_threshold_percent=self.settings.PRICE_DRIFT_THRESHOLD_PERCENT,
            price_drift_min_samples=self.settings.PRICE_DRIFT_MIN_SAMPLES,
            memory_context=memory_contexts,
        )

        action = ProposedFinancialAction(
            user_id=scenario.user_id,
            merchant_id=scenario.merchant_id,
            amount=scenario.amount,
            currency=scenario.currency,
            mandate_id=scenario.mandate_id,
            transaction_type=scenario.transaction_type,
            request_id=uuid.uuid4(),
            requested_at=now,
        )

        return await self.engine.evaluate(action, context)
