"""Serialization and deserialization utilities for synthetic datasets."""

import json
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from experiments.synthetic.models import (
    DatasetManifest,
    SyntheticDataset,
    SyntheticMandateRecord,
    SyntheticMerchantRecord,
    SyntheticPolicyRecord,
    SyntheticScenarioMetadata,
    SyntheticScenarioType,
    SyntheticTransactionRecord,
    SyntheticUserRecord,
)


def serialize_dataset_to_dict(dataset: SyntheticDataset) -> dict[str, Any]:
    """Serialize a SyntheticDataset to a JSON-compatible dictionary."""
    return {
        "manifest": {
            "dataset_id": dataset.manifest.dataset_id,
            "generator_version": dataset.manifest.generator_version,
            "seed": dataset.manifest.seed,
            "scale": dataset.manifest.scale,
            "user_count": dataset.manifest.user_count,
            "merchant_count": dataset.manifest.merchant_count,
            "transaction_count": dataset.manifest.transaction_count,
            "critical_event_count": dataset.manifest.critical_event_count,
            "routine_event_count": dataset.manifest.routine_event_count,
            "scenario_counts": dataset.manifest.scenario_counts,
            "config_summary": dataset.manifest.config_summary,
            "created_at": dataset.manifest.created_at.isoformat(),
        },
        "users": [
            {
                "id": str(u.id),
                "external_reference": u.external_reference,
                "status": u.status,
            }
            for u in dataset.users
        ],
        "merchants": [
            {
                "id": str(m.id),
                "name": m.name,
                "external_reference": m.external_reference,
                "category": m.category,
                "status": m.status,
            }
            for m in dataset.merchants
        ],
        "policies": [
            {
                "id": str(p.id),
                "user_id": str(p.user_id),
                "name": p.name,
                "policy_type": p.policy_type,
                "status": p.status,
                "currency": p.currency,
                "limit_amount": str(p.limit_amount),
                "rules": p.rules,
            }
            for p in dataset.policies
        ],
        "mandates": [
            {
                "id": str(md.id),
                "user_id": str(md.user_id),
                "merchant_id": str(md.merchant_id),
                "status": md.status,
                "currency": md.currency,
                "max_transaction_amount": str(md.max_transaction_amount),
                "valid_from": md.valid_from.isoformat(),
                "valid_until": md.valid_until.isoformat() if md.valid_until else None,
            }
            for md in dataset.mandates
        ],
        "transactions": [
            {
                "id": str(t.id),
                "user_id": str(t.user_id),
                "merchant_id": str(t.merchant_id),
                "amount": str(t.amount),
                "currency": t.currency,
                "mandate_id": str(t.mandate_id) if t.mandate_id else None,
                "transaction_type": t.transaction_type,
                "status": t.status,
                "external_reference": t.external_reference,
                "idempotency_key": t.idempotency_key,
                "occurred_at": t.occurred_at.isoformat(),
                "is_decision_critical": t.is_decision_critical,
                "is_compression_candidate": t.is_compression_candidate,
                "scenario_tag": t.scenario_tag,
                "metadata": t.metadata,
            }
            for t in dataset.transactions
        ],
        "scenarios": [
            {
                "scenario_id": sc.scenario_id,
                "scenario_type": sc.scenario_type.value,
                "user_id": str(sc.user_id),
                "critical_transaction_ids": [
                    str(tid) for tid in sc.critical_transaction_ids
                ],
                "routine_transaction_ids": [
                    str(tid) for tid in sc.routine_transaction_ids
                ],
                "description": sc.description,
                "parameters": sc.parameters,
            }
            for sc in dataset.scenarios
        ],
    }


def deserialize_dataset_from_dict(data: dict[str, Any]) -> SyntheticDataset:
    """Deserialize a dictionary back into a typed SyntheticDataset."""
    mf_data = data["manifest"]
    manifest = DatasetManifest(
        dataset_id=mf_data["dataset_id"],
        generator_version=mf_data.get("generator_version", "1.0.0"),
        seed=int(mf_data["seed"]),
        scale=mf_data.get("scale", "CUSTOM"),
        user_count=int(mf_data["user_count"]),
        merchant_count=int(mf_data["merchant_count"]),
        transaction_count=int(mf_data["transaction_count"]),
        critical_event_count=int(mf_data.get("critical_event_count", 0)),
        routine_event_count=int(mf_data.get("routine_event_count", 0)),
        scenario_counts=mf_data.get("scenario_counts", {}),
        config_summary=mf_data.get("config_summary", {}),
        created_at=datetime.fromisoformat(mf_data["created_at"]),
    )

    users = [
        SyntheticUserRecord(
            id=uuid.UUID(u["id"]),
            external_reference=u["external_reference"],
            status=u.get("status", "ACTIVE"),
        )
        for u in data.get("users", [])
    ]

    merchants = [
        SyntheticMerchantRecord(
            id=uuid.UUID(m["id"]),
            name=m["name"],
            external_reference=m["external_reference"],
            category=m.get("category", "general"),
            status=m.get("status", "ACTIVE"),
        )
        for m in data.get("merchants", [])
    ]

    policies = [
        SyntheticPolicyRecord(
            id=uuid.UUID(p["id"]),
            user_id=uuid.UUID(p["user_id"]),
            name=p["name"],
            policy_type=p.get("policy_type", "TRANSACTION_LIMIT"),
            status=p.get("status", "ACTIVE"),
            currency=p.get("currency", "USD"),
            limit_amount=Decimal(p["limit_amount"]),
            rules=p.get("rules", {}),
        )
        for p in data.get("policies", [])
    ]

    mandates = [
        SyntheticMandateRecord(
            id=uuid.UUID(md["id"]),
            user_id=uuid.UUID(md["user_id"]),
            merchant_id=uuid.UUID(md["merchant_id"]),
            status=md.get("status", "ACTIVE"),
            currency=md.get("currency", "USD"),
            max_transaction_amount=Decimal(
                md.get("max_transaction_amount") or md.get("max_amount", "50.0000")
            ),
            valid_from=datetime.fromisoformat(md["valid_from"]),
            valid_until=datetime.fromisoformat(md["valid_until"])
            if md.get("valid_until")
            else None,
        )
        for md in data.get("mandates", [])
    ]

    transactions = [
        SyntheticTransactionRecord(
            id=uuid.UUID(t["id"]),
            user_id=uuid.UUID(t["user_id"]),
            merchant_id=uuid.UUID(t["merchant_id"]),
            amount=Decimal(t["amount"]),
            currency=t.get("currency", "USD"),
            mandate_id=uuid.UUID(t["mandate_id"]) if t.get("mandate_id") else None,
            transaction_type=t.get("transaction_type", "PURCHASE"),
            status=t.get("status", "CAPTURED"),
            external_reference=t.get("external_reference"),
            idempotency_key=t.get("idempotency_key"),
            occurred_at=datetime.fromisoformat(t["occurred_at"]),
            is_decision_critical=bool(t.get("is_decision_critical", False)),
            is_compression_candidate=bool(t.get("is_compression_candidate", True)),
            scenario_tag=t.get("scenario_tag", "ROUTINE"),
            metadata=t.get("metadata", {}),
        )
        for t in data.get("transactions", [])
    ]

    scenarios = [
        SyntheticScenarioMetadata(
            scenario_id=sc["scenario_id"],
            scenario_type=SyntheticScenarioType(sc["scenario_type"]),
            user_id=uuid.UUID(sc["user_id"]),
            critical_transaction_ids=[
                uuid.UUID(tid) for tid in sc.get("critical_transaction_ids", [])
            ],
            routine_transaction_ids=[
                uuid.UUID(tid) for tid in sc.get("routine_transaction_ids", [])
            ],
            description=sc.get("description", ""),
            parameters=sc.get("parameters", {}),
        )
        for sc in data.get("scenarios", [])
    ]

    return SyntheticDataset(
        manifest=manifest,
        users=users,
        merchants=merchants,
        policies=policies,
        mandates=mandates,
        transactions=transactions,
        scenarios=scenarios,
    )


def save_dataset_to_json(dataset: SyntheticDataset, filepath: str | Path) -> None:
    """Save a SyntheticDataset to a pretty-printed JSON file."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = serialize_dataset_to_dict(dataset)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_dataset_from_json(filepath: str | Path) -> SyntheticDataset:
    """Load a SyntheticDataset from a JSON file."""
    path = Path(filepath)
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return deserialize_dataset_from_dict(payload)
