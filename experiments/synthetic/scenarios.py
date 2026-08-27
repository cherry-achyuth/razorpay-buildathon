"""Scenario generator strategies for synthetic financial history generation."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from experiments.synthetic.models import (
    EventPosition,
    SyntheticMerchantRecord,
    SyntheticScenarioMetadata,
    SyntheticScenarioType,
    SyntheticTransactionRecord,
    SyntheticUserRecord,
)


def _determine_critical_index(total_count: int, position: EventPosition) -> int:
    """Calculate the insertion index for a decision-critical event based on configured position."""
    if total_count <= 1:
        return 0
    if position == EventPosition.EARLY:
        return max(1, int(total_count * 0.25))
    elif position == EventPosition.MIDDLE:
        return max(1, int(total_count * 0.50))
    else:  # LATE or default
        return max(1, total_count - 1)


class ScenarioGenerator:
    """Deterministic scenario builders creating controlled transaction histories."""

    @classmethod
    def generate_routine_purchases(
        cls,
        user: SyntheticUserRecord,
        merchant: SyntheticMerchantRecord,
        count: int,
        base_amount: Decimal,
        currency: str,
        start_time: datetime,
        interval_hours: int = 24,
        scenario_id: str | None = None,
    ) -> tuple[list[SyntheticTransactionRecord], SyntheticScenarioMetadata]:
        """Generate sequence of routine repeated purchases at a single merchant."""
        txs: list[SyntheticTransactionRecord] = []
        sc_id = (
            scenario_id or f"SC_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{user.id}_routine')}"
        )

        for i in range(count):
            tx_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{sc_id}_tx_{i}")
            t = SyntheticTransactionRecord(
                id=tx_id,
                user_id=user.id,
                merchant_id=merchant.id,
                amount=base_amount,
                currency=currency,
                transaction_type="PURCHASE",
                status="CAPTURED",
                external_reference=f"ext_{tx_id}",
                occurred_at=start_time + timedelta(hours=i * interval_hours),
                is_decision_critical=False,
                is_compression_candidate=True,
                scenario_tag=SyntheticScenarioType.ROUTINE_PURCHASE.value,
            )
            txs.append(t)

        meta = SyntheticScenarioMetadata(
            scenario_id=sc_id,
            scenario_type=SyntheticScenarioType.ROUTINE_PURCHASE,
            user_id=user.id,
            critical_transaction_ids=[],
            routine_transaction_ids=[t.id for t in txs],
            description=f"Generated {count} routine captured purchases of {base_amount} {currency}.",
            parameters={
                "merchant_id": str(merchant.id),
                "base_amount": str(base_amount),
            },
        )
        return txs, meta

    @classmethod
    def generate_recurring_subscription(
        cls,
        user: SyntheticUserRecord,
        merchant: SyntheticMerchantRecord,
        count: int,
        subscription_amount: Decimal,
        currency: str,
        start_time: datetime,
        interval_days: int = 30,
        scenario_id: str | None = None,
    ) -> tuple[list[SyntheticTransactionRecord], SyntheticScenarioMetadata]:
        """Generate periodic recurring subscription transactions."""
        txs: list[SyntheticTransactionRecord] = []
        sc_id = scenario_id or f"SC_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{user.id}_sub')}"

        for i in range(count):
            tx_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{sc_id}_tx_{i}")
            t = SyntheticTransactionRecord(
                id=tx_id,
                user_id=user.id,
                merchant_id=merchant.id,
                amount=subscription_amount,
                currency=currency,
                transaction_type="PURCHASE",
                status="CAPTURED",
                external_reference=f"ext_sub_{tx_id}",
                occurred_at=start_time + timedelta(days=i * interval_days),
                is_decision_critical=False,
                is_compression_candidate=True,
                scenario_tag=SyntheticScenarioType.RECURRING_SUBSCRIPTION.value,
            )
            txs.append(t)

        meta = SyntheticScenarioMetadata(
            scenario_id=sc_id,
            scenario_type=SyntheticScenarioType.RECURRING_SUBSCRIPTION,
            user_id=user.id,
            critical_transaction_ids=[],
            routine_transaction_ids=[t.id for t in txs],
            description=f"Generated {count} recurring subscription payments of {subscription_amount} {currency}.",
            parameters={
                "merchant_id": str(merchant.id),
                "amount": str(subscription_amount),
            },
        )
        return txs, meta

    @classmethod
    def generate_price_drift(
        cls,
        user: SyntheticUserRecord,
        merchant: SyntheticMerchantRecord,
        count: int,
        baseline_amount: Decimal,
        drift_amount: Decimal,
        currency: str,
        start_time: datetime,
        position: EventPosition = EventPosition.LATE,
        scenario_id: str | None = None,
    ) -> tuple[list[SyntheticTransactionRecord], SyntheticScenarioMetadata]:
        """Generate history with a significant price spike event placed at target position."""
        txs: list[SyntheticTransactionRecord] = []
        sc_id = (
            scenario_id or f"SC_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{user.id}_drift')}"
        )
        crit_idx = _determine_critical_index(count, position)
        crit_ids: list[uuid.UUID] = []
        routine_ids: list[uuid.UUID] = []

        for i in range(count):
            tx_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{sc_id}_tx_{i}")
            is_crit = i == crit_idx
            amt = drift_amount if is_crit else baseline_amount

            t = SyntheticTransactionRecord(
                id=tx_id,
                user_id=user.id,
                merchant_id=merchant.id,
                amount=amt,
                currency=currency,
                transaction_type="PURCHASE",
                status="CAPTURED",
                external_reference=f"ext_{tx_id}",
                occurred_at=start_time + timedelta(hours=i * 24),
                is_decision_critical=is_crit,
                is_compression_candidate=not is_crit,
                scenario_tag=SyntheticScenarioType.PRICE_DRIFT.value,
                metadata={"drift_event": is_crit},
            )
            txs.append(t)
            if is_crit:
                crit_ids.append(tx_id)
            else:
                routine_ids.append(tx_id)

        meta = SyntheticScenarioMetadata(
            scenario_id=sc_id,
            scenario_type=SyntheticScenarioType.PRICE_DRIFT,
            user_id=user.id,
            critical_transaction_ids=crit_ids,
            routine_transaction_ids=routine_ids,
            description=f"Generated {count} transactions with price drift ({baseline_amount} -> {drift_amount}) at index {crit_idx}.",
            parameters={
                "baseline": str(baseline_amount),
                "drift_amount": str(drift_amount),
                "critical_index": crit_idx,
            },
        )
        return txs, meta

    @classmethod
    def generate_merchant_change(
        cls,
        user: SyntheticUserRecord,
        routine_merchant: SyntheticMerchantRecord,
        new_merchant: SyntheticMerchantRecord,
        count: int,
        amount: Decimal,
        currency: str,
        start_time: datetime,
        position: EventPosition = EventPosition.LATE,
        scenario_id: str | None = None,
    ) -> tuple[list[SyntheticTransactionRecord], SyntheticScenarioMetadata]:
        """Generate history with a shift to an unfamiliar merchant at target position."""
        txs: list[SyntheticTransactionRecord] = []
        sc_id = (
            scenario_id or f"SC_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{user.id}_mchange')}"
        )
        crit_idx = _determine_critical_index(count, position)
        crit_ids: list[uuid.UUID] = []
        routine_ids: list[uuid.UUID] = []

        for i in range(count):
            tx_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{sc_id}_tx_{i}")
            is_crit = i == crit_idx
            m_id = new_merchant.id if is_crit else routine_merchant.id

            t = SyntheticTransactionRecord(
                id=tx_id,
                user_id=user.id,
                merchant_id=m_id,
                amount=amount,
                currency=currency,
                transaction_type="PURCHASE",
                status="CAPTURED",
                external_reference=f"ext_{tx_id}",
                occurred_at=start_time + timedelta(hours=i * 24),
                is_decision_critical=is_crit,
                is_compression_candidate=not is_crit,
                scenario_tag=SyntheticScenarioType.MERCHANT_CHANGE.value,
                metadata={"merchant_change": is_crit, "merchant_id": str(m_id)},
            )
            txs.append(t)
            if is_crit:
                crit_ids.append(tx_id)
            else:
                routine_ids.append(tx_id)

        meta = SyntheticScenarioMetadata(
            scenario_id=sc_id,
            scenario_type=SyntheticScenarioType.MERCHANT_CHANGE,
            user_id=user.id,
            critical_transaction_ids=crit_ids,
            routine_transaction_ids=routine_ids,
            description=f"Generated {count} transactions with merchant transition at index {crit_idx}.",
            parameters={
                "routine_merchant": str(routine_merchant.id),
                "new_merchant": str(new_merchant.id),
            },
        )
        return txs, meta

    @classmethod
    def generate_failed_transaction(
        cls,
        user: SyntheticUserRecord,
        merchant: SyntheticMerchantRecord,
        count: int,
        amount: Decimal,
        currency: str,
        start_time: datetime,
        position: EventPosition = EventPosition.LATE,
        scenario_id: str | None = None,
    ) -> tuple[list[SyntheticTransactionRecord], SyntheticScenarioMetadata]:
        """Generate routine transactions containing a FAILED payment attempt."""
        txs: list[SyntheticTransactionRecord] = []
        sc_id = (
            scenario_id or f"SC_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{user.id}_failed')}"
        )
        crit_idx = _determine_critical_index(count, position)
        crit_ids: list[uuid.UUID] = []
        routine_ids: list[uuid.UUID] = []

        for i in range(count):
            tx_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{sc_id}_tx_{i}")
            is_crit = i == crit_idx
            status = "FAILED" if is_crit else "CAPTURED"

            t = SyntheticTransactionRecord(
                id=tx_id,
                user_id=user.id,
                merchant_id=merchant.id,
                amount=amount,
                currency=currency,
                transaction_type="PURCHASE",
                status=status,
                external_reference=f"ext_{tx_id}",
                occurred_at=start_time + timedelta(hours=i * 24),
                is_decision_critical=is_crit,
                is_compression_candidate=not is_crit,
                scenario_tag=SyntheticScenarioType.FAILED_TRANSACTION.value,
                metadata={"payment_failure": is_crit},
            )
            txs.append(t)
            if is_crit:
                crit_ids.append(tx_id)
            else:
                routine_ids.append(tx_id)

        meta = SyntheticScenarioMetadata(
            scenario_id=sc_id,
            scenario_type=SyntheticScenarioType.FAILED_TRANSACTION,
            user_id=user.id,
            critical_transaction_ids=crit_ids,
            routine_transaction_ids=routine_ids,
            description=f"Generated {count} transactions containing FAILED payment at index {crit_idx}.",
            parameters={"failed_index": crit_idx, "amount": str(amount)},
        )
        return txs, meta

    @classmethod
    def generate_duplicate_like(
        cls,
        user: SyntheticUserRecord,
        merchant: SyntheticMerchantRecord,
        count: int,
        amount: Decimal,
        currency: str,
        start_time: datetime,
        time_delta_seconds: int = 30,
        position: EventPosition = EventPosition.LATE,
        scenario_id: str | None = None,
    ) -> tuple[list[SyntheticTransactionRecord], SyntheticScenarioMetadata]:
        """Generate duplicate-like transactions within 300s window to trigger duplicate detection."""
        txs: list[SyntheticTransactionRecord] = []
        sc_id = scenario_id or f"SC_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{user.id}_dup')}"
        crit_idx = _determine_critical_index(count, position)
        crit_ids: list[uuid.UUID] = []
        routine_ids: list[uuid.UUID] = []

        current_time = start_time
        for i in range(count):
            tx_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{sc_id}_tx_{i}")
            is_crit = i == crit_idx

            if is_crit and i > 0:
                # Place within seconds of preceding transaction
                current_time = txs[-1].occurred_at + timedelta(
                    seconds=time_delta_seconds
                )
            else:
                current_time = start_time + timedelta(hours=i * 24)

            t = SyntheticTransactionRecord(
                id=tx_id,
                user_id=user.id,
                merchant_id=merchant.id,
                amount=amount,
                currency=currency,
                transaction_type="PURCHASE",
                status="CAPTURED",
                external_reference=f"ext_{tx_id}",
                occurred_at=current_time,
                is_decision_critical=is_crit,
                is_compression_candidate=not is_crit,
                scenario_tag=SyntheticScenarioType.DUPLICATE_LIKE.value,
                metadata={"duplicate_pair": is_crit},
            )
            txs.append(t)
            if is_crit:
                crit_ids.append(tx_id)
            else:
                routine_ids.append(tx_id)

        meta = SyntheticScenarioMetadata(
            scenario_id=sc_id,
            scenario_type=SyntheticScenarioType.DUPLICATE_LIKE,
            user_id=user.id,
            critical_transaction_ids=crit_ids,
            routine_transaction_ids=routine_ids,
            description=f"Generated {count} transactions with duplicate-like pair at index {crit_idx} (dt={time_delta_seconds}s).",
            parameters={
                "duplicate_index": crit_idx,
                "delta_seconds": time_delta_seconds,
            },
        )
        return txs, meta
