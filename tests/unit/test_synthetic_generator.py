"""Unit tests for deterministic synthetic dataset generator and serialization."""

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from experiments.synthetic import (
    DatasetConfig,
    DatasetScale,
    EventPosition,
    SyntheticDatasetGenerator,
    SyntheticScenarioType,
    load_dataset_from_json,
    save_dataset_to_json,
    serialize_dataset_to_dict,
)


def test_seed_reproducibility():
    """Test 1: Identical seed and configuration produce identical logical datasets."""
    cfg1 = DatasetConfig(seed=42, scale=DatasetScale.SMALL)
    cfg2 = DatasetConfig(seed=42, scale=DatasetScale.SMALL)

    ds1 = SyntheticDatasetGenerator.generate(cfg1)
    ds2 = SyntheticDatasetGenerator.generate(cfg2)

    # Manifest check
    assert ds1.manifest.seed == ds2.manifest.seed
    assert ds1.manifest.user_count == ds2.manifest.user_count
    assert ds1.manifest.transaction_count == ds2.manifest.transaction_count
    assert ds1.manifest.critical_event_count == ds2.manifest.critical_event_count

    # Content check
    dict1 = serialize_dataset_to_dict(ds1)
    dict2 = serialize_dataset_to_dict(ds2)

    # Disregard creation timestamp in manifest
    dict1["manifest"]["created_at"] = ""
    dict2["manifest"]["created_at"] = ""
    assert dict1 == dict2


def test_different_seeds_produce_different_datasets():
    """Test 2: Distinct seeds produce distinct generated identifiers and data."""
    cfg1 = DatasetConfig(seed=42, scale=DatasetScale.SMALL)
    cfg2 = DatasetConfig(seed=43, scale=DatasetScale.SMALL)

    ds1 = SyntheticDatasetGenerator.generate(cfg1)
    ds2 = SyntheticDatasetGenerator.generate(cfg2)

    assert ds1.users[0].id != ds2.users[0].id
    assert ds1.transactions[0].id != ds2.transactions[0].id
    assert ds1.manifest.dataset_id != ds2.manifest.dataset_id


def test_scale_configurations():
    """Test 3: Verify configured transaction and user counts across scale presets."""
    # Small
    ds_small = SyntheticDatasetGenerator.generate(
        DatasetConfig(seed=10, scale=DatasetScale.SMALL)
    )
    assert len(ds_small.users) == 2
    assert len(ds_small.transactions) == 40  # 2 * 20

    # Medium
    ds_med = SyntheticDatasetGenerator.generate(
        DatasetConfig(seed=10, scale=DatasetScale.MEDIUM)
    )
    assert len(ds_med.users) == 5
    assert len(ds_med.transactions) == 250  # 5 * 50

    # Custom
    ds_custom = SyntheticDatasetGenerator.generate(
        DatasetConfig(
            seed=10,
            scale=DatasetScale.CUSTOM,
            num_users=3,
            transactions_per_user=15,
        )
    )
    assert len(ds_custom.users) == 3
    assert len(ds_custom.transactions) == 45  # 3 * 15


def test_chronological_ordering():
    """Test 4: Verify transactions are strictly sorted chronologically per user."""
    cfg = DatasetConfig(seed=99, scale=DatasetScale.SMALL)
    ds = SyntheticDatasetGenerator.generate(cfg)

    for user in ds.users:
        user_txs = [t for t in ds.transactions if t.user_id == user.id]
        for i in range(len(user_txs) - 1):
            assert user_txs[i].occurred_at <= user_txs[i + 1].occurred_at


def test_financial_precision():
    """Test 5: Verify monetary amounts preserve exact Decimal types and values."""
    cfg = DatasetConfig(
        seed=1,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=10,
        routine_amount=Decimal("19.9900"),
    )
    ds = SyntheticDatasetGenerator.generate(cfg)

    for tx in ds.transactions:
        assert isinstance(tx.amount, Decimal)
        assert tx.amount > Decimal("0.0000")


def test_routine_scenario_generation():
    """Test 6: Routine scenario generates captured purchases with zero critical events."""
    cfg = DatasetConfig(
        seed=5,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=10,
        scenario_mix=[SyntheticScenarioType.ROUTINE_PURCHASE],
    )
    ds = SyntheticDatasetGenerator.generate(cfg)

    assert len(ds.transactions) == 10
    assert all(not t.is_decision_critical for t in ds.transactions)
    assert all(t.is_compression_candidate for t in ds.transactions)
    assert all(t.status == "CAPTURED" for t in ds.transactions)
    assert len(ds.scenarios[0].critical_transaction_ids) == 0


def test_price_drift_scenario_generation():
    """Test 7: Price drift generates routine baseline with an annotated critical price spike."""
    cfg = DatasetConfig(
        seed=7,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=10,
        routine_amount=Decimal("20.0000"),
        scenario_mix=[SyntheticScenarioType.PRICE_DRIFT],
        critical_event_position=EventPosition.LATE,
    )
    ds = SyntheticDatasetGenerator.generate(cfg)

    crit_txs = [t for t in ds.transactions if t.is_decision_critical]
    assert len(crit_txs) == 1
    assert crit_txs[0].amount == Decimal("32.0000")  # 20 * 1.60
    assert crit_txs[0].scenario_tag == SyntheticScenarioType.PRICE_DRIFT.value
    assert len(ds.scenarios[0].critical_transaction_ids) == 1


def test_merchant_change_scenario_generation():
    """Test 8: Merchant change scenario generates transition to unfamiliar merchant."""
    cfg = DatasetConfig(
        seed=8,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=10,
        scenario_mix=[SyntheticScenarioType.MERCHANT_CHANGE],
        critical_event_position=EventPosition.MIDDLE,
    )
    ds = SyntheticDatasetGenerator.generate(cfg)

    crit_txs = [t for t in ds.transactions if t.is_decision_critical]
    assert len(crit_txs) == 1
    # Merchant ID should differ from routine merchant
    routine_m_id = ds.merchants[0].id
    assert crit_txs[0].merchant_id != routine_m_id


def test_failed_transaction_scenario_generation():
    """Test 9: Failed transaction scenario generates FAILED status critical event."""
    cfg = DatasetConfig(
        seed=9,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=8,
        scenario_mix=[SyntheticScenarioType.FAILED_TRANSACTION],
        critical_event_position=EventPosition.EARLY,
    )
    ds = SyntheticDatasetGenerator.generate(cfg)

    failed_txs = [t for t in ds.transactions if t.status == "FAILED"]
    assert len(failed_txs) == 1
    assert failed_txs[0].is_decision_critical is True
    assert failed_txs[0].is_compression_candidate is False


def test_duplicate_like_scenario_generation():
    """Test 10: Duplicate-like scenario generates proximate transactions within 60s."""
    cfg = DatasetConfig(
        seed=10,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=6,
        scenario_mix=[SyntheticScenarioType.DUPLICATE_LIKE],
    )
    ds = SyntheticDatasetGenerator.generate(cfg)

    crit_txs = [t for t in ds.transactions if t.is_decision_critical]
    assert len(crit_txs) == 1
    crit_tx = crit_txs[0]
    # Find preceding transaction
    idx = ds.transactions.index(crit_tx)
    assert idx > 0
    prev_tx = ds.transactions[idx - 1]
    time_diff = (crit_tx.occurred_at - prev_tx.occurred_at).total_seconds()
    assert 0 < time_diff <= 60
    assert crit_tx.amount == prev_tx.amount
    assert crit_tx.merchant_id == prev_tx.merchant_id


def test_policy_boundary_scenario_generation():
    """Test 11: Policy boundary scenario generates below, at, and breach amounts."""
    cfg = DatasetConfig(
        seed=11,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=6,
        policy_limit_amount=Decimal("50.0000"),
        scenario_mix=[SyntheticScenarioType.POLICY_BOUNDARY],
    )
    ds = SyntheticDatasetGenerator.generate(cfg)

    amounts = [t.amount for t in ds.transactions]
    assert Decimal("50.0000") in amounts  # At limit
    assert Decimal("49.0000") in amounts  # Below limit
    assert Decimal("60.0000") in amounts  # Above limit (breach)

    breach_tx = next(t for t in ds.transactions if t.amount == Decimal("60.0000"))
    assert breach_tx.is_decision_critical is True


def test_mixed_history_scenario_generation():
    """Test 12: Mixed history scenario contains routine, failure, drift, and merchant change."""
    cfg = DatasetConfig(
        seed=12,
        scale=DatasetScale.CUSTOM,
        num_users=1,
        transactions_per_user=20,
        scenario_mix=[SyntheticScenarioType.MIXED_HISTORY],
    )
    ds = SyntheticDatasetGenerator.generate(cfg)

    crit_txs = [t for t in ds.transactions if t.is_decision_critical]
    routine_txs = [t for t in ds.transactions if not t.is_decision_critical]

    assert len(crit_txs) == 3  # Failed, merchant change, price drift
    assert len(routine_txs) == 17
    assert any(t.status == "FAILED" for t in crit_txs)


def test_serialization_round_trip():
    """Test 13: Dataset serialization to JSON and back preserves full fidelity."""
    cfg = DatasetConfig(seed=42, scale=DatasetScale.SMALL)
    original_ds = SyntheticDatasetGenerator.generate(cfg)

    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "dataset_roundtrip.json"
        save_dataset_to_json(original_ds, json_path)
        loaded_ds = load_dataset_from_json(json_path)

        assert loaded_ds.manifest.dataset_id == original_ds.manifest.dataset_id
        assert loaded_ds.manifest.seed == original_ds.manifest.seed
        assert len(loaded_ds.users) == len(original_ds.users)
        assert len(loaded_ds.transactions) == len(original_ds.transactions)
        assert len(loaded_ds.scenarios) == len(original_ds.scenarios)

        # Check transaction fields
        for orig_t, load_t in zip(
            original_ds.transactions, loaded_ds.transactions, strict=True
        ):
            assert orig_t.id == load_t.id
            assert orig_t.amount == load_t.amount
            assert orig_t.occurred_at == load_t.occurred_at
            assert orig_t.is_decision_critical == load_t.is_decision_critical
            assert orig_t.scenario_tag == load_t.scenario_tag


def test_critical_event_positioning():
    """Test 14: Critical event placement respects EARLY, MIDDLE, LATE configurations."""
    for pos, expected_idx_range in [
        (EventPosition.EARLY, (1, 4)),
        (EventPosition.MIDDLE, (4, 7)),
        (EventPosition.LATE, (8, 9)),
    ]:
        cfg = DatasetConfig(
            seed=14,
            scale=DatasetScale.CUSTOM,
            num_users=1,
            transactions_per_user=10,
            scenario_mix=[SyntheticScenarioType.PRICE_DRIFT],
            critical_event_position=pos,
        )
        ds = SyntheticDatasetGenerator.generate(cfg)
        crit_tx = next(t for t in ds.transactions if t.is_decision_critical)
        crit_idx = ds.transactions.index(crit_tx)
        assert expected_idx_range[0] <= crit_idx <= expected_idx_range[1]


def test_config_validation_errors():
    """Test 15: Invalid configuration values raise explicit ValueErrors."""
    with pytest.raises(ValueError, match="num_users"):
        SyntheticDatasetGenerator.generate(DatasetConfig(num_users=0))

    with pytest.raises(ValueError, match="transactions_per_user"):
        SyntheticDatasetGenerator.generate(DatasetConfig(transactions_per_user=0))

    with pytest.raises(ValueError, match="policy_limit_amount"):
        SyntheticDatasetGenerator.generate(
            DatasetConfig(policy_limit_amount=Decimal("-10.0000"))
        )

    with pytest.raises(ValueError, match="routine_amount"):
        SyntheticDatasetGenerator.generate(
            DatasetConfig(routine_amount=Decimal("0.0000"))
        )
