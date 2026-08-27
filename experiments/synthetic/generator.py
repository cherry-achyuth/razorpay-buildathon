"""Deterministic seeded synthetic financial dataset generator."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from experiments.synthetic.models import (
    DatasetConfig,
    DatasetManifest,
    DatasetScale,
    SyntheticDataset,
    SyntheticMandateRecord,
    SyntheticMerchantRecord,
    SyntheticPolicyRecord,
    SyntheticScenarioMetadata,
    SyntheticScenarioType,
    SyntheticTransactionRecord,
    SyntheticUserRecord,
)
from experiments.synthetic.scenarios import ScenarioGenerator

logger = logging.getLogger(__name__)


class SyntheticDatasetGenerator:
    """Deterministic seeded generator producing synthetic financial histories with ground truth."""

    VERSION = "1.0.0"

    @classmethod
    def generate(cls, config: DatasetConfig | None = None) -> SyntheticDataset:
        """Generate a complete synthetic dataset adhering to exact deterministic configuration."""
        cfg = config or DatasetConfig()
        cls._validate_config(cfg)

        # 1. Resolve Scale Parameters
        num_users, tx_per_user = cls._resolve_scale(cfg)

        # 2. Deterministically Generate Merchants
        merchants = cls._generate_merchants(cfg.seed)

        # 3. Deterministically Generate Users, Policies, Mandates, and Scenarios
        users: list[SyntheticUserRecord] = []
        policies: list[SyntheticPolicyRecord] = []
        mandates: list[SyntheticMandateRecord] = []
        all_transactions: list[SyntheticTransactionRecord] = []
        all_scenarios: list[SyntheticScenarioMetadata] = []

        scenario_palette = cfg.scenario_mix or [
            SyntheticScenarioType.ROUTINE_PURCHASE,
            SyntheticScenarioType.RECURRING_SUBSCRIPTION,
            SyntheticScenarioType.PRICE_DRIFT,
            SyntheticScenarioType.MERCHANT_CHANGE,
            SyntheticScenarioType.FAILED_TRANSACTION,
            SyntheticScenarioType.DUPLICATE_LIKE,
            SyntheticScenarioType.POLICY_BOUNDARY,
            SyntheticScenarioType.MIXED_HISTORY,
        ]

        for user_idx in range(num_users):
            user_id = uuid.uuid5(
                uuid.NAMESPACE_DNS, f"synth_user_{cfg.seed}_{user_idx}"
            )
            user = SyntheticUserRecord(
                id=user_id,
                external_reference=f"synthetic_user_{user_idx + 1:04d}",
                status="ACTIVE",
            )
            users.append(user)

            # Generate Standard Policy (Limit $50.00 USD)
            policy_id = uuid.uuid5(
                uuid.NAMESPACE_DNS, f"synth_policy_{cfg.seed}_{user_idx}"
            )
            policy = SyntheticPolicyRecord(
                id=policy_id,
                user_id=user_id,
                name=f"Policy Limit for User {user_idx + 1}",
                policy_type="TRANSACTION_LIMIT",
                status="ACTIVE",
                currency=cfg.default_currency,
                limit_amount=cfg.policy_limit_amount,
                rules={},
            )
            policies.append(policy)

            # Generate Standard Mandate
            mandate_id = uuid.uuid5(
                uuid.NAMESPACE_DNS, f"synth_mandate_{cfg.seed}_{user_idx}"
            )
            mandate = SyntheticMandateRecord(
                id=mandate_id,
                user_id=user_id,
                merchant_id=merchants[0].id,
                status="ACTIVE",
                currency=cfg.default_currency,
                max_transaction_amount=cfg.policy_limit_amount,
                valid_from=cfg.base_timestamp,
                valid_until=None,
            )
            mandates.append(mandate)

            # Assign Scenario Type for this user
            sc_type = scenario_palette[user_idx % len(scenario_palette)]
            user_txs, user_meta = cls._generate_user_history(
                user=user,
                merchants=merchants,
                scenario_type=sc_type,
                tx_count=tx_per_user,
                config=cfg,
                user_offset_days=user_idx * 5,
            )

            all_transactions.extend(user_txs)
            all_scenarios.append(user_meta)

        # 4. Sort all transactions chronologically per user
        all_transactions.sort(key=lambda t: (t.user_id, t.occurred_at, t.id))

        # 5. Compute Manifest Statistics
        crit_count = sum(1 for t in all_transactions if t.is_decision_critical)
        routine_count = sum(1 for t in all_transactions if not t.is_decision_critical)

        sc_counts: dict[str, int] = {}
        for sc in all_scenarios:
            tag = sc.scenario_type.value
            sc_counts[tag] = sc_counts.get(tag, 0) + 1

        manifest = DatasetManifest(
            dataset_id=f"SYNTH_DS_{cfg.seed}_{cfg.scale.value}_{len(all_transactions)}",
            generator_version=cls.VERSION,
            seed=cfg.seed,
            scale=cfg.scale.value,
            user_count=len(users),
            merchant_count=len(merchants),
            transaction_count=len(all_transactions),
            critical_event_count=crit_count,
            routine_event_count=routine_count,
            scenario_counts=sc_counts,
            config_summary={
                "seed": cfg.seed,
                "scale": cfg.scale.value,
                "num_users": num_users,
                "transactions_per_user": tx_per_user,
                "default_currency": cfg.default_currency,
                "critical_position": cfg.critical_event_position.value,
            },
            created_at=datetime.now(UTC),
        )

        return SyntheticDataset(
            manifest=manifest,
            users=users,
            merchants=merchants,
            policies=policies,
            mandates=mandates,
            transactions=all_transactions,
            scenarios=all_scenarios,
        )

    @classmethod
    def _validate_config(cls, cfg: DatasetConfig) -> None:
        """Validate input configuration for strict boundaries."""
        if cfg.num_users < 1:
            raise ValueError(f"num_users must be at least 1, got {cfg.num_users}")
        if cfg.transactions_per_user < 1:
            raise ValueError(
                f"transactions_per_user must be at least 1, got {cfg.transactions_per_user}"
            )
        if cfg.policy_limit_amount <= Decimal("0.0000"):
            raise ValueError(
                f"policy_limit_amount must be positive, got {cfg.policy_limit_amount}"
            )
        if cfg.routine_amount <= Decimal("0.0000"):
            raise ValueError(
                f"routine_amount must be positive, got {cfg.routine_amount}"
            )

    @classmethod
    def _resolve_scale(cls, cfg: DatasetConfig) -> tuple[int, int]:
        """Resolve scale presets if not custom."""
        if cfg.scale == DatasetScale.SMALL:
            return 2, 20
        elif cfg.scale == DatasetScale.MEDIUM:
            return 5, 50
        elif cfg.scale == DatasetScale.LARGE:
            return 10, 100
        else:  # CUSTOM
            return cfg.num_users, cfg.transactions_per_user

    @classmethod
    def _generate_merchants(cls, seed: int) -> list[SyntheticMerchantRecord]:
        """Generate deterministic standard catalog of merchant counterparties."""
        merchant_templates = [
            ("Daily Grind Coffee", "merchant_coffee_01", "food_and_beverage"),
            ("CloudStream Subscription", "merchant_stream_01", "entertainment"),
            ("Acme Cloud Hosting", "merchant_hosting_01", "technology"),
            ("Global Retail Marketplace", "merchant_retail_01", "retail"),
            ("Unfamiliar Novel Merchant", "merchant_unfam_01", "unknown"),
        ]

        merchants: list[SyntheticMerchantRecord] = []
        for idx, (name, ref, cat) in enumerate(merchant_templates):
            m_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"synth_merchant_{seed}_{idx}")
            merchants.append(
                SyntheticMerchantRecord(
                    id=m_id,
                    name=name,
                    external_reference=ref,
                    category=cat,
                    status="ACTIVE",
                )
            )
        return merchants

    @classmethod
    def _generate_user_history(
        cls,
        user: SyntheticUserRecord,
        merchants: list[SyntheticMerchantRecord],
        scenario_type: SyntheticScenarioType,
        tx_count: int,
        config: DatasetConfig,
        user_offset_days: int,
    ) -> tuple[list[SyntheticTransactionRecord], SyntheticScenarioMetadata]:
        """Generate controlled transaction history and metadata for a specific scenario type."""
        m_routine = merchants[0]
        m_sub = merchants[1]
        m_unfam = merchants[4]
        start_time = config.base_timestamp + timedelta(days=user_offset_days)

        if scenario_type == SyntheticScenarioType.ROUTINE_PURCHASE:
            return ScenarioGenerator.generate_routine_purchases(
                user=user,
                merchant=m_routine,
                count=tx_count,
                base_amount=config.routine_amount,
                currency=config.default_currency,
                start_time=start_time,
            )

        elif scenario_type == SyntheticScenarioType.RECURRING_SUBSCRIPTION:
            return ScenarioGenerator.generate_recurring_subscription(
                user=user,
                merchant=m_sub,
                count=tx_count,
                subscription_amount=Decimal("15.0000"),
                currency=config.default_currency,
                start_time=start_time,
            )

        elif scenario_type == SyntheticScenarioType.PRICE_DRIFT:
            drift_amount = round(config.routine_amount * Decimal("1.60"), 4)
            return ScenarioGenerator.generate_price_drift(
                user=user,
                merchant=m_routine,
                count=tx_count,
                baseline_amount=config.routine_amount,
                drift_amount=drift_amount,
                currency=config.default_currency,
                start_time=start_time,
                position=config.critical_event_position,
            )

        elif scenario_type == SyntheticScenarioType.MERCHANT_CHANGE:
            return ScenarioGenerator.generate_merchant_change(
                user=user,
                routine_merchant=m_routine,
                new_merchant=m_unfam,
                count=tx_count,
                amount=config.routine_amount,
                currency=config.default_currency,
                start_time=start_time,
                position=config.critical_event_position,
            )

        elif scenario_type == SyntheticScenarioType.FAILED_TRANSACTION:
            return ScenarioGenerator.generate_failed_transaction(
                user=user,
                merchant=m_routine,
                count=tx_count,
                amount=config.routine_amount,
                currency=config.default_currency,
                start_time=start_time,
                position=config.critical_event_position,
            )

        elif scenario_type == SyntheticScenarioType.DUPLICATE_LIKE:
            return ScenarioGenerator.generate_duplicate_like(
                user=user,
                merchant=m_routine,
                count=tx_count,
                amount=config.routine_amount,
                currency=config.default_currency,
                start_time=start_time,
                time_delta_seconds=30,
                position=config.critical_event_position,
            )

        elif scenario_type == SyntheticScenarioType.POLICY_BOUNDARY:
            # Generate mix around policy boundary: below ($49.00), at ($50.00), and above ($55.00)
            txs: list[SyntheticTransactionRecord] = []
            sc_id = f"SC_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{user.id}_policy_boundary')}"
            crit_ids: list[uuid.UUID] = []
            routine_ids: list[uuid.UUID] = []

            for i in range(tx_count):
                tx_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{sc_id}_tx_{i}")
                # Inject policy breach at target position
                is_crit = i == tx_count - 1
                amt = (
                    config.policy_limit_amount + Decimal("10.0000")
                    if is_crit
                    else (
                        config.policy_limit_amount
                        if i % 2 == 0
                        else config.policy_limit_amount - Decimal("1.0000")
                    )
                )

                t = SyntheticTransactionRecord(
                    id=tx_id,
                    user_id=user.id,
                    merchant_id=m_routine.id,
                    amount=amt,
                    currency=config.default_currency,
                    transaction_type="PURCHASE",
                    status="CAPTURED",
                    external_reference=f"ext_{tx_id}",
                    occurred_at=start_time + timedelta(hours=i * 24),
                    is_decision_critical=is_crit,
                    is_compression_candidate=not is_crit,
                    scenario_tag=SyntheticScenarioType.POLICY_BOUNDARY.value,
                    metadata={"policy_boundary_amount": str(amt)},
                )
                txs.append(t)
                if is_crit:
                    crit_ids.append(tx_id)
                else:
                    routine_ids.append(tx_id)

            meta = SyntheticScenarioMetadata(
                scenario_id=sc_id,
                scenario_type=SyntheticScenarioType.POLICY_BOUNDARY,
                user_id=user.id,
                critical_transaction_ids=crit_ids,
                routine_transaction_ids=routine_ids,
                description=f"Generated {tx_count} transactions evaluating policy boundary limits.",
                parameters={"policy_limit": str(config.policy_limit_amount)},
            )
            return txs, meta

        else:  # MIXED_HISTORY
            # Realistic mixture: routine + failed + price drift + merchant change
            txs: list[SyntheticTransactionRecord] = []
            sc_id = f"SC_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{user.id}_mixed')}"
            crit_ids: list[uuid.UUID] = []
            routine_ids: list[uuid.UUID] = []

            for i in range(tx_count):
                tx_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{sc_id}_tx_{i}")
                # Pattern: mostly routine, with 1 failed at 25%, 1 merchant change at 50%, 1 price drift at 75%
                is_failed = i == int(tx_count * 0.25)
                is_mchange = i == int(tx_count * 0.50)
                is_drift = i == int(tx_count * 0.75)
                is_crit = is_failed or is_mchange or is_drift

                m_id = m_unfam.id if is_mchange else m_routine.id
                status = "FAILED" if is_failed else "CAPTURED"
                amt = (
                    config.routine_amount * Decimal("1.80")
                    if is_drift
                    else config.routine_amount
                )

                t = SyntheticTransactionRecord(
                    id=tx_id,
                    user_id=user.id,
                    merchant_id=m_id,
                    amount=amt,
                    currency=config.default_currency,
                    transaction_type="PURCHASE",
                    status=status,
                    external_reference=f"ext_{tx_id}",
                    occurred_at=start_time + timedelta(hours=i * 24),
                    is_decision_critical=is_crit,
                    is_compression_candidate=not is_crit,
                    scenario_tag=SyntheticScenarioType.MIXED_HISTORY.value,
                    metadata={
                        "is_failed": is_failed,
                        "is_mchange": is_mchange,
                        "is_drift": is_drift,
                    },
                )
                txs.append(t)
                if is_crit:
                    crit_ids.append(tx_id)
                else:
                    routine_ids.append(tx_id)

            meta = SyntheticScenarioMetadata(
                scenario_id=sc_id,
                scenario_type=SyntheticScenarioType.MIXED_HISTORY,
                user_id=user.id,
                critical_transaction_ids=crit_ids,
                routine_transaction_ids=routine_ids,
                description=f"Generated {tx_count} transactions with realistic mixed routine and critical events.",
                parameters={"critical_count": len(crit_ids)},
            )
            return txs, meta
