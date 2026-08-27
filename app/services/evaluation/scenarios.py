"""Scenario definitions and deterministic scenario factory for decision-preservation evaluation."""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.models.enums import DecisionOutcome, TransactionType


@dataclass(frozen=True)
class EvaluationScenarioDefinition:
    """Deterministic financial scenario definition for comparative evaluation."""

    scenario_id: str
    name: str
    user_id: uuid.UUID
    merchant_id: uuid.UUID
    amount: Decimal
    currency: str
    mandate_id: uuid.UUID | None = None
    transaction_type: TransactionType = TransactionType.PURCHASE
    expected_full_decision: DecisionOutcome | None = None
    category: str = "GENERAL"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ScenarioFactory:
    """Factory generating deterministic, reproducible benchmark test scenarios."""

    @classmethod
    def create_standard_scenarios(
        cls,
        user_id: uuid.UUID,
        routine_merchant_id: uuid.UUID,
        unfamiliar_merchant_id: uuid.UUID,
        mandate_id: uuid.UUID | None = None,
        policy_limit_amount: Decimal = Decimal("50.0000"),
        routine_baseline_amount: Decimal = Decimal("25.0000"),
    ) -> list[EvaluationScenarioDefinition]:
        """Generate standard 5-scenario suite for basic decision-preservation checks."""
        # 1. Routine Repeated Purchase (Within historical baseline and policy)
        s1 = EvaluationScenarioDefinition(
            scenario_id="SCENARIO_ROUTINE_PURCHASE",
            name="Routine Repeated Purchase",
            user_id=user_id,
            merchant_id=routine_merchant_id,
            amount=routine_baseline_amount,
            currency="USD",
            mandate_id=mandate_id,
            category="ROUTINE",
            expected_full_decision=DecisionOutcome.ALLOW,
            description="Routine payment matching familiar counterparty and baseline amount.",
        )

        # 2. Policy Limit Breach (Amount exceeds authoritative policy)
        s2 = EvaluationScenarioDefinition(
            scenario_id="SCENARIO_POLICY_BREACH",
            name="Policy Limit Breach",
            user_id=user_id,
            merchant_id=routine_merchant_id,
            amount=policy_limit_amount + Decimal("50.0000"),
            currency="USD",
            mandate_id=mandate_id,
            category="POLICY_BOUNDARY",
            expected_full_decision=DecisionOutcome.BLOCK,
            description="Amount strictly exceeds maximum allowable policy limit.",
        )

        # 3. Significant Price Drift (+60% above historical baseline)
        drift_amount = round(routine_baseline_amount * Decimal("1.60"), 4)
        s3 = EvaluationScenarioDefinition(
            scenario_id="SCENARIO_SIGNIFICANT_PRICE_DRIFT",
            name="Significant Price Drift",
            user_id=user_id,
            merchant_id=routine_merchant_id,
            amount=drift_amount,
            currency="USD",
            mandate_id=mandate_id,
            category="PRICE_DRIFT",
            expected_full_decision=DecisionOutcome.ASK_USER,
            description="Price is 60% higher than historical baseline (exceeds 25% threshold).",
        )

        # 4. Price Drift Within Bounds (+10% above historical baseline)
        within_bounds_amount = round(routine_baseline_amount * Decimal("1.10"), 4)
        s4 = EvaluationScenarioDefinition(
            scenario_id="SCENARIO_PRICE_WITHIN_BOUNDS",
            name="Price Drift Within Bounds",
            user_id=user_id,
            merchant_id=routine_merchant_id,
            amount=within_bounds_amount,
            currency="USD",
            mandate_id=mandate_id,
            category="PRICE_DRIFT",
            expected_full_decision=DecisionOutcome.ALLOW,
            description="Price is 10% higher than baseline, which is within the 25% tolerance.",
        )

        # 5. Unexpected Merchant Change (Unfamiliar counterparty for established user)
        s5 = EvaluationScenarioDefinition(
            scenario_id="SCENARIO_UNEXPECTED_MERCHANT",
            name="Unexpected Merchant Change",
            user_id=user_id,
            merchant_id=unfamiliar_merchant_id,
            amount=routine_baseline_amount,
            currency="USD",
            category="MERCHANT_CHANGE",
            expected_full_decision=DecisionOutcome.ASK_USER,
            description="Proposed merchant is unfamiliar and differs from established history.",
        )

        return [s1, s2, s3, s4, s5]

    @classmethod
    def create_adversarial_scenarios(
        cls,
        user_id: uuid.UUID,
        routine_merchant_id: uuid.UUID,
        unfamiliar_merchant_id: uuid.UUID,
        secondary_known_merchant_id: uuid.UUID | None = None,
        similar_name_merchant_id: uuid.UUID | None = None,
        mandate_id: uuid.UUID | None = None,
        policy_limit_amount: Decimal = Decimal("50.0000"),
        routine_baseline_amount: Decimal = Decimal("25.0000"),
        drift_threshold_percent: Decimal = Decimal("25.0"),
    ) -> list[EvaluationScenarioDefinition]:
        """Generate comprehensive adversarial and boundary scenario suite for stress testing."""
        scenarios: list[EvaluationScenarioDefinition] = []

        # ======================================================================
        # Category A: POLICY LIMIT BOUNDARIES
        # ======================================================================
        # A1. Exactly at policy limit ($50.0000) -> <= limit -> ALLOW
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_POLICY_EXACT_AT_LIMIT",
                name="Policy Boundary: Exactly At Limit",
                user_id=user_id,
                merchant_id=routine_merchant_id,
                amount=policy_limit_amount,
                currency="USD",
                mandate_id=mandate_id,
                category="POLICY_BOUNDARY",
                expected_full_decision=DecisionOutcome.ALLOW,
                description="Amount matches the policy limit exactly (edge boundary <=).",
            )
        )

        # A2. Just below policy limit ($49.9900) -> < limit -> ALLOW
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_POLICY_JUST_BELOW_LIMIT",
                name="Policy Boundary: Just Below Limit",
                user_id=user_id,
                merchant_id=routine_merchant_id,
                amount=policy_limit_amount - Decimal("0.0100"),
                currency="USD",
                mandate_id=mandate_id,
                category="POLICY_BOUNDARY",
                expected_full_decision=DecisionOutcome.ALLOW,
                description="Amount is $0.01 below policy limit.",
            )
        )

        # A3. Just above policy limit ($50.0100) -> > limit -> BLOCK
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_POLICY_JUST_ABOVE_LIMIT",
                name="Policy Boundary: Just Above Limit",
                user_id=user_id,
                merchant_id=routine_merchant_id,
                amount=policy_limit_amount + Decimal("0.0100"),
                currency="USD",
                mandate_id=mandate_id,
                category="POLICY_BOUNDARY",
                expected_full_decision=DecisionOutcome.BLOCK,
                description="Amount is $0.01 above policy limit, triggering hard policy block.",
            )
        )

        # ======================================================================
        # Category B: PRICE DRIFT BOUNDARIES
        # Baseline = $25.0000, Threshold = 25.0%
        # ======================================================================
        # B1. Exactly at price drift threshold (+25.0% = $31.2500). Rule checks `drift > 25.0%` -> ALLOW
        at_threshold_amount = round(
            routine_baseline_amount
            * (Decimal("1.0") + (drift_threshold_percent / Decimal("100.0"))),
            4,
        )
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_PRICE_DRIFT_EXACT_AT_THRESHOLD",
                name="Price Drift: Exactly At Threshold",
                user_id=user_id,
                merchant_id=routine_merchant_id,
                amount=at_threshold_amount,
                currency="USD",
                mandate_id=mandate_id,
                category="PRICE_DRIFT_BOUNDARY",
                expected_full_decision=DecisionOutcome.ALLOW,
                description="Price drift equals threshold exactly (+25.00%). Boundary is not exceeded.",
            )
        )

        # B2. Just below price drift threshold (+24.0% = $31.0000) -> ALLOW
        below_threshold_amount = round(
            routine_baseline_amount
            * (
                Decimal("1.0")
                + ((drift_threshold_percent - Decimal("1.0")) / Decimal("100.0"))
            ),
            4,
        )
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_PRICE_DRIFT_JUST_BELOW_THRESHOLD",
                name="Price Drift: Just Below Threshold",
                user_id=user_id,
                merchant_id=routine_merchant_id,
                amount=below_threshold_amount,
                currency="USD",
                mandate_id=mandate_id,
                category="PRICE_DRIFT_BOUNDARY",
                expected_full_decision=DecisionOutcome.ALLOW,
                description="Price drift is 1% below threshold (+24.00%).",
            )
        )

        # B3. Just above price drift threshold (+26.0% = $31.5000) -> ASK_USER
        above_threshold_amount = round(
            routine_baseline_amount
            * (
                Decimal("1.0")
                + ((drift_threshold_percent + Decimal("1.0")) / Decimal("100.0"))
            ),
            4,
        )
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_PRICE_DRIFT_JUST_ABOVE_THRESHOLD",
                name="Price Drift: Just Above Threshold",
                user_id=user_id,
                merchant_id=routine_merchant_id,
                amount=above_threshold_amount,
                currency="USD",
                mandate_id=mandate_id,
                category="PRICE_DRIFT_BOUNDARY",
                expected_full_decision=DecisionOutcome.ASK_USER,
                description="Price drift is 1% above threshold (+26.00%), triggering confirmation prompt.",
            )
        )

        # ======================================================================
        # Category C: MERCHANT CHANGE & IDENTITY
        # ======================================================================
        # C1. Familiar repeated merchant -> ALLOW
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_MERCHANT_FAMILIAR_REPEATED",
                name="Merchant: Familiar Repeated Counterparty",
                user_id=user_id,
                merchant_id=routine_merchant_id,
                amount=routine_baseline_amount,
                currency="USD",
                mandate_id=mandate_id,
                category="MERCHANT_IDENTITY",
                expected_full_decision=DecisionOutcome.ALLOW,
                description="Payment to familiar routine merchant with known transaction history.",
            )
        )

        # C2. Unfamiliar changed merchant -> ASK_USER
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_MERCHANT_UNFAMILIAR_CHANGE",
                name="Merchant: Unfamiliar Counterparty Change",
                user_id=user_id,
                merchant_id=unfamiliar_merchant_id,
                amount=routine_baseline_amount,
                currency="USD",
                category="MERCHANT_IDENTITY",
                expected_full_decision=DecisionOutcome.ASK_USER,
                description="Payment to unfamiliar merchant for established user.",
            )
        )

        # C3. Secondary known merchant if provided
        sec_m_id = secondary_known_merchant_id or uuid.uuid4()
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_MERCHANT_SECONDARY_KNOWN",
                name="Merchant: Secondary Known Counterparty",
                user_id=user_id,
                merchant_id=sec_m_id,
                amount=routine_baseline_amount,
                currency="USD",
                mandate_id=mandate_id,
                category="MERCHANT_IDENTITY",
                description="Payment to a secondary merchant in user's multi-merchant portfolio.",
            )
        )

        # C4. Similar name but distinct UUID
        sim_m_id = similar_name_merchant_id or uuid.uuid4()
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_MERCHANT_SIMILAR_NAME_DIFFERENT_ID",
                name="Merchant: Similar Name Different ID",
                user_id=user_id,
                merchant_id=sim_m_id,
                amount=routine_baseline_amount,
                currency="USD",
                category="MERCHANT_IDENTITY",
                expected_full_decision=DecisionOutcome.ASK_USER,
                description="Merchant has similar name but distinct UUID counterparty ID.",
            )
        )

        # ======================================================================
        # Category D: REDUNDANCY STRESS & CRITICAL EXCEPTIONS
        # ======================================================================
        # D1. Redundant routine purchase
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_REDUNDANCY_ROUTINE_PURCHASE",
                name="Redundancy Stress: Routine Purchase",
                user_id=user_id,
                merchant_id=routine_merchant_id,
                amount=routine_baseline_amount,
                currency="USD",
                mandate_id=mandate_id,
                category="REDUNDANCY_STRESS",
                expected_full_decision=DecisionOutcome.ALLOW,
                description="Routine payment evaluated against highly compressed multi-event history.",
            )
        )

        # D2. Redundancy with severe price spike (+100% = $50.0000) -> ASK_USER
        spike_amount = round(routine_baseline_amount * Decimal("2.0000"), 4)
        scenarios.append(
            EvaluationScenarioDefinition(
                scenario_id="SCENARIO_REDUNDANCY_WITH_PRICE_SPIKE",
                name="Redundancy Stress: Severe Price Spike",
                user_id=user_id,
                merchant_id=routine_merchant_id,
                amount=spike_amount,
                currency="USD",
                mandate_id=mandate_id,
                category="CRITICAL_EXCEPTION",
                expected_full_decision=DecisionOutcome.ASK_USER,
                description="Severe +100% price spike evaluated against compressed routine history.",
            )
        )

        return scenarios
