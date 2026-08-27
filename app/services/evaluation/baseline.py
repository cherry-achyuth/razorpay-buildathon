"""Full-history deterministic baseline evaluator."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ResourceNotFoundError
from app.models.enums import PolicyStatus, TransactionStatus
from app.models.mandate import Mandate
from app.models.merchant import Merchant
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.models.user import User
from app.services.evaluation.scenarios import EvaluationScenarioDefinition
from app.services.guardrails.base import EvaluationContext, ProposedFinancialAction
from app.services.guardrails.engine import (
    DeterministicRuleEngine,
    EngineEvaluationResult,
)

logger = logging.getLogger(__name__)


class FullHistoryBaselineEvaluator:
    """Evaluates financial decisions based strictly on authoritative raw PostgreSQL history.

    Rules and Invariants:
    1. Does NOT use DecisionMemory.
    2. Does NOT use vector embeddings or semantic search.
    3. Does NOT use generative AI or LLMs.
    4. Evaluates purely through the deterministic financial rule engine.
    """

    def __init__(self, engine: DeterministicRuleEngine | None = None) -> None:
        self.engine = engine or DeterministicRuleEngine()
        self.settings = get_settings()

    async def evaluate_scenario(
        self,
        scenario: EvaluationScenarioDefinition,
        db: AsyncSession,
        as_of: datetime | None = None,
    ) -> EngineEvaluationResult:
        """Run deterministic decision evaluation using complete raw financial history."""
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

        # 5. Load Raw Duplicate Detection Window Transactions
        dup_window_s = self.settings.DUPLICATE_DETECTION_WINDOW_SECONDS
        dup_start = now - timedelta(seconds=dup_window_s)
        dup_query = select(Transaction).where(
            Transaction.user_id == scenario.user_id,
            Transaction.occurred_at >= dup_start,
        )
        dup_res = await db.execute(dup_query)
        recent_window_txs = list(dup_res.scalars().all())

        # 6. Load Raw Merchant Historical Transactions
        price_query = (
            select(Transaction)
            .where(
                Transaction.user_id == scenario.user_id,
                Transaction.merchant_id == scenario.merchant_id,
                Transaction.currency == scenario.currency,
                Transaction.transaction_type == scenario.transaction_type,
                Transaction.status.in_(
                    [TransactionStatus.CAPTURED, TransactionStatus.AUTHORIZED]
                ),
            )
            .order_by(Transaction.occurred_at.desc())
            .limit(50)
        )
        price_res = await db.execute(price_query)
        merchant_hist_txs = list(price_res.scalars().all())

        # 7. Load Raw User Counterparties
        user_merchants_query = (
            select(Transaction.merchant_id)
            .where(
                Transaction.user_id == scenario.user_id,
                Transaction.status.in_(
                    [TransactionStatus.CAPTURED, TransactionStatus.AUTHORIZED]
                ),
            )
            .distinct()
        )
        merchants_res = await db.execute(user_merchants_query)
        user_merchant_ids = set(merchants_res.scalars().all())

        # 8. Load Total Historical Transaction Count
        count_query = select(func.count(Transaction.id)).where(
            Transaction.user_id == scenario.user_id,
            Transaction.status.in_(
                [TransactionStatus.CAPTURED, TransactionStatus.AUTHORIZED]
            ),
        )
        user_tx_count = await db.scalar(count_query) or 0

        # 9. Build Baseline Evaluation Context (memory_context is explicitly empty)
        context = EvaluationContext(
            user=user,
            merchant=merchant,
            mandate=mandate,
            active_policies=active_policies,
            recent_window_transactions=recent_window_txs,
            merchant_historical_transactions=merchant_hist_txs,
            user_historical_merchant_ids=user_merchant_ids,
            user_total_historical_tx_count=user_tx_count,
            existing_idempotency_record=None,
            duplicate_window_seconds=dup_window_s,
            price_drift_threshold_percent=self.settings.PRICE_DRIFT_THRESHOLD_PERCENT,
            price_drift_min_samples=self.settings.PRICE_DRIFT_MIN_SAMPLES,
            memory_context=[],  # ZERO memory in full-history baseline
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
