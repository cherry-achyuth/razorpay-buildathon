"""Payment execution service orchestrating guardrails, decision gates, and Razorpay Test Mode."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models.audit import AuditLog
from app.models.decision import Decision
from app.models.enums import (
    AuditEventType,
    DecisionOutcome,
    MemoryRelevance,
    MemoryStatus,
    MemoryType,
    MerchantStatus,
    TransactionStatus,
    TransactionType,
    UserStatus,
)
from app.models.memory import DecisionMemory
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.decision import ActionEvaluationRequest
from app.schemas.payment import (
    DecisionConfirmationRequest,
    DecisionConfirmationResponse,
    PaymentExecutionRequest,
    PaymentExecutionResponse,
)
from app.services.audit.service import AuditLogService
from app.services.decision_service import DecisionEvaluationService
from app.services.payment.client import RazorpayTestClient

logger = logging.getLogger(__name__)


class PaymentExecutionService:
    """Service controlling the financial authorization and payment execution gate."""

    def __init__(
        self,
        decision_service: DecisionEvaluationService | None = None,
        razorpay_client: RazorpayTestClient | None = None,
    ) -> None:
        self.decision_service = decision_service or DecisionEvaluationService()
        self.razorpay_client = razorpay_client or RazorpayTestClient()

    async def execute_payment(
        self,
        payload: PaymentExecutionRequest,
        db: AsyncSession,
    ) -> PaymentExecutionResponse:
        """Evaluates financial action against deterministic guardrails and executes payment if ALLOW."""
        payment_id = uuid.uuid4()
        now = datetime.now(UTC)

        # 1. Verify User exists and is active
        user = await db.get(User, payload.user_id)
        if not user or user.status != UserStatus.ACTIVE:
            raise AppException(
                message=f"User with ID {payload.user_id} does not exist or is inactive",
                error_code="USER_NOT_FOUND",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # 2. Verify Merchant exists and is active
        merchant = await db.get(Merchant, payload.merchant_id)
        if not merchant or merchant.status != MerchantStatus.ACTIVE:
            raise AppException(
                message=f"Merchant with ID {payload.merchant_id} does not exist or is inactive",
                error_code="MERCHANT_NOT_FOUND",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # 3. Log initial audit request
        await AuditLogService.append_event(
            db=db,
            event_type=AuditEventType.PAYMENT_REQUESTED,
            entity_type="PAYMENT_REQUEST",
            entity_id=payment_id,
            user_id=payload.user_id,
            event_data={
                "payment_id": str(payment_id),
                "merchant_id": str(payload.merchant_id),
                "amount": str(payload.amount),
                "currency": payload.currency,
                "idempotency_key": payload.idempotency_key,
            },
            occurred_at=now,
        )

        # 4. Evaluate Financial Action via Deterministic Guardrails
        eval_request = ActionEvaluationRequest(
            user_id=payload.user_id,
            merchant_id=payload.merchant_id,
            mandate_id=payload.mandate_id,
            amount=payload.amount,
            currency=payload.currency,
            transaction_type=payload.transaction_type,
            idempotency_key=payload.idempotency_key,
            request_id=payment_id,
            metadata=payload.metadata,
        )
        eval_response = await self.decision_service.evaluate_action(eval_request, db)

        # Find the created Decision ID if recorded
        decision_stmt = (
            select(Decision.id)
            .where(Decision.request_reference == str(payment_id))
            .order_by(Decision.created_at.desc())
            .limit(1)
        )
        decision_id = await db.scalar(decision_stmt)

        # ----------------------------------------------------------------------
        # Decision Gate 1: BLOCK -> Hard Stop, Zero Money Movement
        # ----------------------------------------------------------------------
        if eval_response.decision == DecisionOutcome.BLOCK:
            await AuditLogService.append_event(
                db=db,
                event_type=AuditEventType.PAYMENT_FAILED,
                entity_type="PAYMENT",
                entity_id=payment_id,
                user_id=payload.user_id,
                event_data={
                    "payment_id": str(payment_id),
                    "decision": "BLOCK",
                    "reason_code": eval_response.reason_code,
                    "reason": eval_response.reason,
                },
                occurred_at=datetime.now(UTC),
            )
            await db.commit()
            return PaymentExecutionResponse(
                payment_id=payment_id,
                user_id=payload.user_id,
                merchant_id=payload.merchant_id,
                amount=payload.amount,
                currency=payload.currency,
                decision=DecisionOutcome.BLOCK,
                status="BLOCKED",
                decision_id=decision_id,
                transaction_id=None,
                gateway_order_id=None,
                gateway_payment_id=None,
                gateway_mode=self._gateway_mode_string(),
                reason_code=eval_response.reason_code,
                reason=eval_response.reason,
                rule_results=eval_response.rule_results,
                executed_at=datetime.now(UTC),
            )

        # ----------------------------------------------------------------------
        # Decision Gate 2: ASK_USER -> Halt until explicit user confirmation
        # ----------------------------------------------------------------------
        if eval_response.decision == DecisionOutcome.ASK_USER:
            # Check if this specific decision was already confirmed by user
            is_pre_confirmed = False
            target_dec_id = payload.decision_id or decision_id
            if target_dec_id:
                dec_rec = await db.get(Decision, target_dec_id)
                if dec_rec:
                    ev = dec_rec.evidence_metadata or {}
                    if ev.get("user_confirmed") or payload.decision_id is not None:
                        is_pre_confirmed = True
                        ev["user_confirmed"] = True
                        dec_rec.evidence_metadata = ev
                        await db.flush()

            if not is_pre_confirmed:
                await db.commit()
                return PaymentExecutionResponse(
                    payment_id=payment_id,
                    user_id=payload.user_id,
                    merchant_id=payload.merchant_id,
                    amount=payload.amount,
                    currency=payload.currency,
                    decision=DecisionOutcome.ASK_USER,
                    status="REQUIRES_USER_CONFIRMATION",
                    decision_id=decision_id,
                    transaction_id=None,
                    gateway_order_id=None,
                    gateway_payment_id=None,
                    gateway_mode=self._gateway_mode_string(),
                    reason_code=eval_response.reason_code,
                    reason=eval_response.reason,
                    rule_results=eval_response.rule_results,
                    executed_at=datetime.now(UTC),
                )

        # ----------------------------------------------------------------------
        # Decision Gate 3: ALLOW -> Execute Razorpay Test Mode Payment
        # ----------------------------------------------------------------------
        await AuditLogService.append_event(
            db=db,
            event_type=AuditEventType.PAYMENT_ATTEMPTED,
            entity_type="PAYMENT",
            entity_id=payment_id,
            user_id=payload.user_id,
            event_data={
                "payment_id": str(payment_id),
                "decision": "ALLOW",
                "amount": str(payload.amount),
                "currency": payload.currency,
            },
            occurred_at=datetime.now(UTC),
        )

        try:
            rzp_order = await self.razorpay_client.create_order(
                amount=payload.amount,
                currency=payload.currency,
                receipt=f"rcpt_{str(payment_id)[:20]}",
                notes={
                    "user_id": str(payload.user_id),
                    "merchant_id": str(payload.merchant_id),
                    "decision_vault_payment_id": str(payment_id),
                },
            )

            # Persist authoritative Transaction record
            tx = Transaction(
                id=uuid.uuid4(),
                user_id=payload.user_id,
                merchant_id=payload.merchant_id,
                mandate_id=payload.mandate_id,
                amount=payload.amount,
                currency=payload.currency,
                transaction_type=payload.transaction_type,
                status=TransactionStatus.CAPTURED,
                external_reference=rzp_order.order_id,
                idempotency_key=payload.idempotency_key,
                occurred_at=datetime.now(UTC),
            )
            db.add(tx)
            await db.flush()

            # Record Payment Success in Audit Chain
            await AuditLogService.append_event(
                db=db,
                event_type=AuditEventType.PAYMENT_SUCCEEDED,
                entity_type="TRANSACTION",
                entity_id=tx.id,
                user_id=payload.user_id,
                event_data={
                    "payment_id": str(payment_id),
                    "transaction_id": str(tx.id),
                    "order_id": rzp_order.order_id,
                    "gateway_mode": rzp_order.gateway_mode,
                    "amount": str(payload.amount),
                    "currency": payload.currency,
                },
                occurred_at=tx.occurred_at,
            )

            # Auto-build decision memory from captured transaction (Issue 4)
            from app.services.memory.builder import MemoryBuilderService

            try:
                await MemoryBuilderService.build_from_transaction(
                    transaction_id=tx.id,
                    db=db,
                    requested_user_id=payload.user_id,
                )
            except Exception as mem_err:
                logger.warning(
                    "Failed to auto-build decision memory for tx %s: %s",
                    tx.id,
                    mem_err,
                )

            await db.commit()

            return PaymentExecutionResponse(
                payment_id=payment_id,
                user_id=payload.user_id,
                merchant_id=payload.merchant_id,
                amount=payload.amount,
                currency=payload.currency,
                decision=DecisionOutcome.ALLOW,
                status="SUCCESS",
                decision_id=decision_id,
                transaction_id=tx.id,
                gateway_order_id=rzp_order.order_id,
                gateway_payment_id=f"pay_{uuid.uuid4().hex[:14]}",
                gateway_mode=rzp_order.gateway_mode,
                reason_code=eval_response.reason_code,
                reason=eval_response.reason,
                rule_results=eval_response.rule_results,
                executed_at=tx.occurred_at,
            )

        except Exception as exc:
            logger.error("Payment execution error: %s", exc, exc_info=True)
            # Record failed transaction in PostgreSQL
            failed_tx = Transaction(
                id=uuid.uuid4(),
                user_id=payload.user_id,
                merchant_id=payload.merchant_id,
                mandate_id=payload.mandate_id,
                amount=payload.amount,
                currency=payload.currency,
                transaction_type=payload.transaction_type,
                status=TransactionStatus.FAILED,
                external_reference=f"err_{str(payment_id)[:16]}",
                idempotency_key=payload.idempotency_key,
                occurred_at=datetime.now(UTC),
            )
            db.add(failed_tx)
            await db.flush()

            await AuditLogService.append_event(
                db=db,
                event_type=AuditEventType.PAYMENT_FAILED,
                entity_type="TRANSACTION",
                entity_id=failed_tx.id,
                user_id=payload.user_id,
                event_data={
                    "payment_id": str(payment_id),
                    "transaction_id": str(failed_tx.id),
                    "error": str(exc),
                },
                occurred_at=failed_tx.occurred_at,
            )
            await db.commit()

            return PaymentExecutionResponse(
                payment_id=payment_id,
                user_id=payload.user_id,
                merchant_id=payload.merchant_id,
                amount=payload.amount,
                currency=payload.currency,
                decision=DecisionOutcome.ALLOW,
                status="FAILED",
                decision_id=decision_id,
                transaction_id=failed_tx.id,
                gateway_order_id=None,
                gateway_payment_id=None,
                gateway_mode=self._gateway_mode_string(),
                reason_code="GATEWAY_ERROR",
                reason=f"Payment execution failed at gateway: {exc}",
                rule_results=eval_response.rule_results,
                executed_at=datetime.now(UTC),
            )

    async def confirm_decision(
        self,
        decision_id: uuid.UUID,
        confirmation: DecisionConfirmationRequest,
        db: AsyncSession,
    ) -> DecisionConfirmationResponse:
        """Processes user confirmation for an ASK_USER decision, optionally executing payment."""
        decision = await db.get(Decision, decision_id)
        if not decision:
            stmt = (
                select(Decision)
                .where(Decision.request_reference == str(decision_id))
                .order_by(Decision.created_at.desc())
                .limit(1)
            )
            decision = await db.scalar(stmt)

        if not decision:
            raise AppException(
                message=f"Decision with ID {decision_id} does not exist",
                error_code="DECISION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        now = datetime.now(UTC)
        meta = dict(decision.evidence_metadata or {})
        meta["user_confirmed"] = confirmation.confirmed
        meta["confirmed_at"] = now.isoformat()
        if confirmation.user_notes:
            meta["user_notes"] = confirmation.user_notes
        decision.evidence_metadata = meta

        payment_res: PaymentExecutionResponse | None = None
        baseline_updated = False
        new_baseline_amount: Decimal | None = None

        if not confirmation.confirmed:
            await AuditLogService.append_event(
                db=db,
                event_type=AuditEventType.PAYMENT_FAILED,
                entity_type="DECISION",
                entity_id=decision.id,
                user_id=decision.user_id,
                event_data={
                    "decision_id": str(decision.id),
                    "action": "REJECTED_BY_USER",
                    "user_notes": confirmation.user_notes,
                    "reason": "Payment rejected by user upon ASK_USER confirmation.",
                },
                occurred_at=now,
            )

        if confirmation.confirmed:
            user_id = decision.user_id
            req_amount = Decimal(str(meta.get("requested_amount", "0")))
            req_curr = meta.get("currency", "INR")

            # Resolve merchant
            target_merchant_id = None
            raw_m_id = meta.get("merchant_id")
            if raw_m_id:
                try:
                    target_merchant_id = uuid.UUID(str(raw_m_id))
                except ValueError:
                    pass

            if not target_merchant_id and meta.get("merchant_name"):
                m_stmt = select(Merchant).where(Merchant.name == meta["merchant_name"])
                found_m = await db.scalar(m_stmt)
                if found_m:
                    target_merchant_id = found_m.id

            if not target_merchant_id:
                stmt_m = select(Merchant.id).limit(1)
                target_merchant_id = await db.scalar(stmt_m) or uuid.uuid4()

            merchant_obj = await db.get(Merchant, target_merchant_id)
            m_label = (
                merchant_obj.name
                if merchant_obj
                else meta.get("merchant_name", "Merchant")
            )

            # ----------------------------------------------------------------------
            # Confirmed Baseline Update (Human-Authorized Permanent Shift)
            # ----------------------------------------------------------------------
            if confirmation.accept_as_new_baseline and req_amount > Decimal("0.0000"):
                # Anti-Ratcheting Safeguard: Cooldown Window Check (7 days)
                cooldown_window = timedelta(days=7)
                recent_update_stmt = (
                    select(AuditLog)
                    .where(
                        AuditLog.user_id == user_id,
                        AuditLog.event_type == AuditEventType.BASELINE_UPDATED,
                        AuditLog.occurred_at >= now - cooldown_window,
                    )
                    .order_by(AuditLog.occurred_at.desc())
                )
                recent_updates = (await db.scalars(recent_update_stmt)).all()
                has_recent_update = any(
                    u.event_data.get("merchant_id") == str(target_merchant_id)
                    for u in recent_updates
                )

                if has_recent_update:
                    raise AppException(
                        message=(
                            "Baseline update rejected by anti-ratcheting safeguard: "
                            "A baseline price change for this merchant was already confirmed within the 7-day cooldown window. "
                            "To prevent gradual price manipulation, further updates require a full evaluation cycle."
                        ),
                        error_code="BASELINE_UPDATE_COOLDOWN_ACTIVE",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )

                # Supersede prior active routine memories for this merchant
                old_baseline = meta.get("historical_baseline")
                active_mems = (
                    await db.scalars(
                        select(DecisionMemory).where(
                            DecisionMemory.user_id == user_id,
                            DecisionMemory.status == MemoryStatus.ACTIVE,
                        )
                    )
                ).all()
                for mem in active_mems:
                    if (
                        str(mem.structured_data.get("merchant_id"))
                        == str(target_merchant_id)
                        and mem.structured_data.get("currency") == req_curr
                    ):
                        if not old_baseline:
                            old_baseline = mem.structured_data.get("avg_amount")
                        mem.status = MemoryStatus.SUPERSEDED

                # Create new user-confirmed baseline DecisionMemory
                new_memory = DecisionMemory(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    memory_type=MemoryType.ROUTINE_PATTERN,
                    relevance=MemoryRelevance.NORMAL,
                    status=MemoryStatus.ACTIVE,
                    summary=(
                        f"User-confirmed updated baseline price for {m_label}: "
                        f"{req_amount:.2f} {req_curr} (updated from {old_baseline or 'unspecified'} {req_curr})"
                    ),
                    structured_data={
                        "merchant_id": str(target_merchant_id),
                        "merchant_name": m_label,
                        "currency": req_curr,
                        "avg_amount": str(req_amount),
                        "last_amount": str(req_amount),
                        "source_event_count": 5,
                        "confirmed_by_user": True,
                        "baseline_updated_at": now.isoformat(),
                    },
                    valid_from=now,
                    valid_until=now + timedelta(days=365),
                )
                db.add(new_memory)
                await db.flush()

                # Append Hash-Chained Audit Log Event
                await AuditLogService.append_event(
                    db=db,
                    event_type=AuditEventType.BASELINE_UPDATED,
                    entity_type="MERCHANT_BASELINE",
                    entity_id=target_merchant_id,
                    user_id=user_id,
                    event_data={
                        "merchant_id": str(target_merchant_id),
                        "merchant_name": m_label,
                        "old_baseline": str(old_baseline) if old_baseline else None,
                        "new_baseline": str(req_amount),
                        "currency": req_curr,
                        "decision_id": str(decision_id),
                        "confirmed_by": "USER",
                        "timestamp": now.isoformat(),
                    },
                    occurred_at=now,
                )

                baseline_updated = True
                new_baseline_amount = req_amount

            # ----------------------------------------------------------------------
            # Payment Execution (if execute_payment_now is True)
            # ----------------------------------------------------------------------
            if confirmation.execute_payment_now and req_amount > Decimal("0.0000"):
                # Execute Razorpay payment directly after confirmation
                rzp_order = await self.razorpay_client.create_order(
                    amount=req_amount,
                    currency=req_curr,
                    receipt=f"rcpt_conf_{str(decision_id)[:16]}",
                    notes={
                        "user_id": str(user_id),
                        "decision_id": str(decision_id),
                        "confirmed": True,
                    },
                )

                tx = Transaction(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    merchant_id=target_merchant_id,
                    amount=req_amount,
                    currency=req_curr,
                    transaction_type=TransactionType.PURCHASE,
                    status=TransactionStatus.CAPTURED,
                    external_reference=rzp_order.order_id,
                    occurred_at=now,
                )
                db.add(tx)
                await db.flush()

                await AuditLogService.append_event(
                    db=db,
                    event_type=AuditEventType.PAYMENT_SUCCEEDED,
                    entity_type="TRANSACTION",
                    entity_id=tx.id,
                    user_id=user_id,
                    event_data={
                        "decision_id": str(decision_id),
                        "transaction_id": str(tx.id),
                        "order_id": rzp_order.order_id,
                        "gateway_mode": rzp_order.gateway_mode,
                        "confirmed_by_user": True,
                    },
                    occurred_at=now,
                )

                payment_res = PaymentExecutionResponse(
                    payment_id=uuid.uuid4(),
                    user_id=user_id,
                    merchant_id=target_merchant_id,
                    amount=req_amount,
                    currency=req_curr,
                    decision=DecisionOutcome.ALLOW,
                    status="SUCCESS",
                    decision_id=decision_id,
                    transaction_id=tx.id,
                    gateway_order_id=rzp_order.order_id,
                    gateway_payment_id=f"pay_{uuid.uuid4().hex[:14]}",
                    gateway_mode=rzp_order.gateway_mode,
                    reason_code="USER_CONFIRMED",
                    reason="Transaction authorized by user confirmation.",
                    rule_results=[],
                    executed_at=now,
                )

        await db.commit()

        msg = "Payment successfully executed after user confirmation."
        if baseline_updated:
            msg += f" Permanent price baseline for {m_label} updated to {new_baseline_amount} {req_curr}."

        return DecisionConfirmationResponse(
            decision_id=decision_id,
            status="CONFIRMED" if confirmation.confirmed else "REJECTED_BY_USER",
            confirmed=confirmation.confirmed,
            baseline_updated=baseline_updated,
            new_baseline_amount=new_baseline_amount,
            payment_result=payment_res,
            message=msg if confirmation.confirmed else "Payment rejected by user.",
            updated_at=now,
        )

    def _gateway_mode_string(self) -> str:
        return (
            "RAZORPAY_TEST_MODE"
            if self.razorpay_client.is_configured
            else "SANDBOX_SIMULATION"
        )
