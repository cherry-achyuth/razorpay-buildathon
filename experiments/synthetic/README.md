# DecisionVault Synthetic Financial Dataset Infrastructure

> **Deterministic, Reproducible Financial History Generator with Ground-Truth Annotations**

This module provides the empirical dataset generation layer for evaluating DecisionVault's memory compression and decision preservation without modifying production decision engines or compromising sensitive customer data.

---

## 1. Why Synthetic Data Exists

To evaluate whether compressed `DecisionMemory` preserves financial decisions relative to complete raw PostgreSQL history:
1. Experiments require **strictly controlled financial histories** where the exact nature, placement, and quantity of critical vs. routine events are mathematically known.
2. Compression preservation rates cannot be rigorously measured without explicit ground-truth labeling distinguishing routine candidates for compression from safety-critical anomalies.

---

## 2. Why Production Data Is Not Used

- **Privacy & Security**: Production financial transactions contain sensitive PII, account numbers, and merchant relationships that cannot be stored in experiment fixtures.
- **Reproducibility**: Production data constantly mutates; empirical benchmarks require bitwise deterministic test inputs across repeated evaluation cycles.
- **Ground-Truth Ambiguity**: In production data, subtle price drift or merchant shifts are not explicitly labeled, confounding compression evaluation with classification uncertainty.

---

## 3. What the Generator Does Not Represent

- Synthetic datasets do **not** model real-world macroeconomic consumer spending distributions or complex fraud topologies.
- Ground truth represents the **experimental design configuration**, not a universal financial decision rule. Authoritative decisions remain the exclusive responsibility of DecisionVault's deterministic guardrail rule engine.

---

## 4. Controlled Scenario Classes

| Scenario Class | Description | Ground Truth Status |
| :--- | :--- | :--- |
| `ROUTINE_PURCHASE` | Repeated stable purchases at familiar merchant ($25.00) | `is_decision_critical = False`, `is_compression_candidate = True` |
| `RECURRING_SUBSCRIPTION` | Periodic monthly subscription charges ($15.00) | `is_decision_critical = False`, `is_compression_candidate = True` |
| `PRICE_DRIFT` | Stable baseline ($25.00) with a +60% price spike ($40.00) | `is_decision_critical = True`, `is_compression_candidate = False` |
| `MERCHANT_CHANGE` | Established merchant history transitioned to unfamiliar counterparty | `is_decision_critical = True`, `is_compression_candidate = False` |
| `FAILED_TRANSACTION` | Routine history containing a `FAILED` payment attempt | `is_decision_critical = True`, `is_compression_candidate = False` |
| `DUPLICATE_LIKE` | Identical transactions occurring within 30s window | `is_decision_critical = True`, `is_compression_candidate = False` |
| `POLICY_BOUNDARY` | Transactions below ($49.00), at ($50.00), and above ($60.00) policy limit | `is_decision_critical = True` (on breach) |
| `MIXED_HISTORY` | Realistic blend of routine, subscription, failure, drift, and merchant change | Explicitly annotated per event |

---

## 5. Reproducibility & Seed Protocol

Given the identical `seed` and `DatasetConfig`, `SyntheticDatasetGenerator.generate(config)` produces identical:
- User & Merchant UUIDs (deterministic `uuid5` based on seed and index)
- Transaction timestamps, amounts, currencies, and statuses
- Ground-truth critical vs. routine event references

```python
from experiments.synthetic import DatasetConfig, DatasetScale, SyntheticDatasetGenerator

config = DatasetConfig(seed=42, scale=DatasetScale.SMALL)
dataset = SyntheticDatasetGenerator.generate(config)
```

---

## 6. Future Use in Day 14 Experiments

Day 14 decision-preservation experiments will consume datasets produced by this generator to:
1. Seed PostgreSQL test databases across configurable scales (100, 1,000, 10,000 transactions).
2. Execute dual-path evaluation (`FullHistoryBaselineEvaluator` vs. `CompressedMemoryEvaluator`).
3. Compute empirical compression ratios, decision preservation rates, safety-critical preservation rates, and critical-memory recall without hard-coded assumptions.
