"""Regression coverage for package-safety upstream receipt binding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.packaging import PackageReceiptV2

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "package-receipts"


def test_safety_receipt_rejects_non_json_upstream_package_receipt_mappings() -> None:
    upstream_receipt = PackageReceiptV2.model_validate(
        json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))
    )
    assert upstream_receipt.candidate is not None
    assert upstream_receipt.package_digest is not None
    payload = {
        "schema_version": "package-safety-evidence/v1",
        "receipt_id": "package-safety-review-1234",
        "candidate": upstream_receipt.candidate.model_dump(mode="json"),
        "lane": "safety_review",
        "input_receipt_id": upstream_receipt.receipt_id,
        "package_digest": upstream_receipt.package_digest,
        "reviewer": {
            "adapter_id": "review/manual",
            "adapter_version_or_digest": "v1",
            "method": "manual_review",
        },
        "status": "not_reviewed",
        "observed_at": "2026-08-30T14:00:00Z",
        "evidence": [],
        "findings": [],
        "blocker": None,
        "blockers": [],
        "mutation_performed": False,
        "rights_decision_performed": False,
        "admission_performed": False,
    }
    raw_upstream_receipt = upstream_receipt.model_dump(mode="json")
    raw_upstream_receipt["receipt_id"] = b"synthetic-package-receipt-2"

    with pytest.raises(ContractError, match="invalid_json_value"):
        SchemaRegistry().validate_package_safety_evidence_against_package_receipt(payload, raw_upstream_receipt)
