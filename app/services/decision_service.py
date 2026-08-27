"""Decision evaluation service orchestrating context and rule execution."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppException
from app.models.decision import Decision
from app.models.enums import (
    DecisionOutcome,
    MemorySourceType,
    MemoryStatus,
    MerchantStatus,
    PolicyStatus,
    TransactionStatus,
    UserStatus,
)
from app.models.idempotency import IdempotencyRecord
from app.models.mandate import Mandate
from app.models.merchant import Merchant
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.decision import (
    ActionEvaluationRequest,
    ActionEvaluationResponse,
    DecisionMemoryContextResponse,
    RuleResultSchema,
)
from app.schemas.memory import MemorySourceSchema
from app.services.guardrails.base import (
    DecisionMemoryContext,
    EvaluationContext,
    ProposedFinancialAction,
)
from app.services.guardrails.engine import DeterministicRuleEngine
from app.services.memory.retrieval import MemoryRetrievalService

logger = logging.getLogger(__name__)


class DecisionEvaluationService:
    """Orchestrates policy evaluation against authoritative PostgreSQL state."""

    def __init__(self, engine: DeterministicRuleEngine | None = None) -> None:
        self.engine = engine or DeterministicRuleEngine()
        self.settings = get_settings()

    async def evaluate_action(
        self,
        payload: ActionEvaluationRequest,
        db: AsyncSession,
    ) -> ActionEvaluationResponse:
        """Evaluates a proposed action without executing payment or moving funds."""
        # 1. Authoritative User context lookup
        user = await db.get(User, payload.user_id)
        if not user or user.status != UserStatus.ACTIVE:
            req_id = payload.request_id or uuid.uuid4()
            return ActionEvaluationResponse(
                request_id=req_id,
                decision_id=None,
                decision=DecisionOutcome.BLOCK,
                reason_code="USER_NOT_FOUND",
                reason="User account does not exist or is inactive.",
                rule_results=[],
                memory_context=[],
                evaluated_at=datetime.now(UTC),
            )

        # 2. Authoritative Merchant context lookup
        merchant = await db.get(Merchant, payload.merchant_id)
        if not merchant or merchant.status != MerchantStatus.ACTIVE:
            req_id = payload.request_id or uuid.uuid4()
            return ActionEvaluationResponse(
                request_id=req_id,
                decision_id=None,
                decision=DecisionOutcome.BLOCK,
                reason_code="MERCHANT_NOT_FOUND",
                reason="Merchant does not exist or is inactive.",
                rule_results=[],
                memory_context=[],
                evaluated_at=datetime.now(UTC),
            )

        # 3. Authoritative Mandate context lookup if provided
        mandate: Mandate | None = None
        if payload.mandate_id:
            mandate = await db.get(Mandate, payload.mandate_id)
            if not mandate:
                raise AppException(
                    message=f"Mandate with ID {payload.mandate_id} does not exist",
                    error_code="MANDATE_NOT_FOUND",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

        # 4. Build ProposedFinancialAction
        request_id = payload.request_id or uuid.uuid4()
        now = datetime.now(UTC)
        action = ProposedFinancialAction(
            user_id=payload.user_id,
            merchant_id=payload.merchant_id,
            mandate_id=payload.mandate_id,
            amount=payload.amount,
            currency=payload.currency,
            transaction_type=payload.transaction_type,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            requested_at=now,
            metadata=payload.metadata or {},
        )

        # 5. Check Idempotency Record if key is supplied
        existing_idempotency: IdempotencyRecord | None = None
        if action.idempotency_key:
            idem_query = select(IdempotencyRecord).where(
                IdempotencyRecord.key == action.idempotency_key
            )
            existing_idempotency = await db.scalar(idem_query)

            if existing_idempotency:
                canonical_hash = action.canonical_fingerprint()
                if canonical_hash == existing_idempotency.request_hash:
                    # Identical replay: safely return previous deterministic result
                    return ActionEvaluationResponse.model_validate(
                        existing_idempotency.response_payload
                    )

        # 6. Retrieve User-Scoped Decision Memory Context (Observable & Bounded)
        memory_contexts: list[DecisionMemoryContext] = []
        try:
            active_memories = await MemoryRetrievalService.get_user_memories(
                user_id=payload.user_id,
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
                "Decision memory retrieval failed for user_id=%s: %s",
                payload.user_id,
                exc,
                exc_info=True,
            )
            # Fall back to empty memory context; hard deterministic guardrails continue.
            memory_contexts = []

        # 7. Authoritative Active Policies lookup
        policies_query = select(Policy).where(
            Policy.user_id == payload.user_id,
            Policy.status == PolicyStatus.ACTIVE,
        )
        policies_result = await db.execute(policies_query)
        active_policies = list(policies_result.scalars().all())

        # 8. Targeted Duplicate Window Historical Query
        dup_window_s = self.settings.DUPLICATE_DETECTION_WINDOW_SECONDS
        dup_start = now - timedelta(seconds=dup_window_s)
        dup_query = select(Transaction).where(
            Transaction.user_id == payload.user_id,
            Transaction.occurred_at >= dup_start,
        )
        dup_result = await db.execute(dup_query)
        recent_window_txs = list(dup_result.scalars().all())

        # 9. Targeted Merchant Price History Query
        price_query = (
            select(Transaction)
            .where(
                Transaction.user_id == payload.user_id,
                Transaction.merchant_id == payload.merchant_id,
                Transaction.currency == payload.currency,
                Transaction.transaction_type == payload.transaction_type,
                Transaction.status.in_(
                    [TransactionStatus.CAPTURED, TransactionStatus.AUTHORIZED]
                ),
            )
            .order_by(Transaction.occurred_at.desc())
            .limit(20)
        )
        price_result = await db.execute(price_query)
        merchant_hist_txs = list(price_result.scalars().all())

        # 10. Targeted User Merchant History Query
        user_merchants_query = (
            select(Transaction.merchant_id)
            .where(
                Transaction.user_id == payload.user_id,
                Transaction.status.in_(
                    [TransactionStatus.CAPTURED, TransactionStatus.AUTHORIZED]
                ),
            )
            .distinct()
            .limit(50)
        )
        merchants_res = await db.execute(user_merchants_query)
        user_merchant_ids = set(merchants_res.scalars().all())

        user_count_query = select(func.count(Transaction.id)).where(
            Transaction.user_id == payload.user_id,
            Transaction.status.in_(
                [TransactionStatus.CAPTURED, TransactionStatus.AUTHORIZED]
            ),
        )
        user_tx_count = await db.scalar(user_count_query) or 0

        # 11. Build Enriched EvaluationContext
        context = EvaluationContext(
            user=user,
            merchant=merchant,
            mandate=mandate,
            active_policies=active_policies,
            recent_window_transactions=recent_window_txs,
            merchant_historical_transactions=merchant_hist_txs,
            user_historical_merchant_ids=user_merchant_ids,
            user_total_historical_tx_count=user_tx_count,
            existing_idempotency_record=existing_idempotency,
            duplicate_window_seconds=dup_window_s,
            price_drift_threshold_percent=self.settings.PRICE_DRIFT_THRESHOLD_PERCENT,
            price_drift_min_samples=self.settings.PRICE_DRIFT_MIN_SAMPLES,
            memory_context=memory_contexts,
        )

        # 12. Execute Deterministic Guardrails Engine
        engine_result = await self.engine.evaluate(action, context)

        # 13. Convert rule results to schema representation
        rule_results_schemas = [
            RuleResultSchema(
                rule_id=r.rule_id,
                status=r.status,
                decision_effect=r.decision_effect,
                reason_code=r.reason_code,
                message=r.message,
                evidence=r.evidence,
                severity=r.severity,
            )
            for r in engine_result.rule_results
        ]

        memory_context_schemas = [
            DecisionMemoryContextResponse(
                memory_id=mc.memory_id,
                memory_type=mc.memory_type,
                relevance=mc.relevance,
                summary=mc.summary,
                structured_data=mc.structured_data,
                sources=[
                    MemorySourceSchema(
                        id=s.id or uuid.uuid4(),
                        memory_id=s.memory_id or mc.memory_id,
                        source_type=MemorySourceType(s.source_type),
                        source_id=s.source_id,
                        created_at=s.created_at or (mc.created_at or now),
                    )
                    for s in mc.sources
                ],
            )
            for mc in memory_contexts
        ]

        response = ActionEvaluationResponse(
            request_id=request_id,
            decision=engine_result.decision,
            reason_code=engine_result.reason_code,
            reason=engine_result.reason,
            rule_results=rule_results_schemas,
            memory_context=memory_context_schemas,
            evaluated_at=datetime.now(UTC),
        )

        # 14. Record evaluation decision trace and idempotency record
        decision_record = Decision(
            user_id=user.id,
            transaction_id=None,  # No transaction exists at evaluation stage
            request_reference=str(request_id),
            decision=engine_result.decision,
            reason=engine_result.reason,
            evidence_metadata={
                "reason_code": engine_result.reason_code,
                "merchant_id": str(action.merchant_id),
                "merchant_name": merchant.name,
                "requested_amount": str(action.amount),
                "currency": action.currency,
                "historical_baseline": next(
                    (
                        r.evidence.get("historical_baseline")
                        for r in engine_result.rule_results
                        if r.evidence and r.evidence.get("historical_baseline")
                    ),
                    None,
                ),
                "idempotency_key": action.idempotency_key,
                "memory_context": [
                    {
                        "memory_id": str(mc.memory_id),
                        "memory_type": mc.memory_type.value,
                        "relevance": mc.relevance.value,
                        "summary": mc.summary,
                    }
                    for mc in memory_contexts
                ],
                "rule_results": [
                    {
                        "rule_id": r.rule_id,
                        "status": r.status.value,
                        "decision_effect": r.decision_effect.value,
                        "reason_code": r.reason_code,
                        "message": r.message,
                        "evidence": r.evidence,
                        "severity": r.severity.value,
                    }
                    for r in engine_result.rule_results
                ],
            },
        )

        try:
            db.add(decision_record)
            await db.flush()
            response.decision_id = decision_record.id

            if action.idempotency_key and not existing_idempotency:
                idempotency_entry = IdempotencyRecord(
                    key=action.idempotency_key,
                    user_id=user.id,
                    request_hash=action.canonical_fingerprint(),
                    response_payload=response.model_dump(mode="json"),
                )
                db.add(idempotency_entry)

            # 15. Append Tamper-Evident Audit Event
            from app.models.enums import AuditEventType
            from app.services.audit.service import AuditLogService

            await AuditLogService.append_event(
                db=db,
                event_type=AuditEventType.DECISION_EVALUATED,
                entity_type="DECISION",
                entity_id=decision_record.id,
                user_id=user.id,
                event_data={
                    "request_id": str(request_id),
                    "decision_id": str(decision_record.id),
                    "decision": engine_result.decision.value,
                    "reason_code": engine_result.reason_code,
                    "amount": str(action.amount),
                    "currency": action.currency,
                    "merchant_id": str(action.merchant_id),
                    "memory_count": len(memory_contexts),
                    "rule_count": len(engine_result.rule_results),
                },
                occurred_at=response.evaluated_at,
            )

            await db.flush()
        except IntegrityError:
            await db.rollback()
            # Handle race condition where concurrent request inserted the same key
            if action.idempotency_key:
                for _ in range(15):
                    await asyncio.sleep(0.05)
                    row = await db.execute(
                        text(
                            "SELECT request_hash, response_payload "
                            "FROM idempotency_records WHERE key = :k"
                        ),
                        {"k": action.idempotency_key},
                    )
                    record = row.first()
                    if record:
                        req_hash, resp_raw = record[0], record[1]
                        if isinstance(resp_raw, str):
                            resp_payload = json.loads(resp_raw)
                        else:
                            resp_payload = resp_raw
                        if req_hash == action.canonical_fingerprint():
                            return ActionEvaluationResponse.model_validate(resp_payload)
            raise

        return response
