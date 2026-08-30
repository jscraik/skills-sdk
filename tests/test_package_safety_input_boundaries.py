"""Direct-input boundary regressions for package safety evidence."""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.safety import PackageSafetyEvidenceReceipt


def _payload() -> dict[str, object]:
    return {
        "schema_version": "package-safety-evidence/v1",
        "receipt_id": "package-safety-review-1234",
        "candidate": {
            "schema_version": "package-candidate/v1",
            "package_id": "synthetic-skill",
            "source_revision": "1" * 40,
            "content_sha256": "a" * 64,
        },
        "lane": "safety_review",
        "input_receipt_id": "package-receipt-1234",
        "package_digest": "a" * 64,
        "reviewer": {
            "adapter_id": "review/manual",
            "adapter_version_or_digest": "v1",
            "method": "manual_review",
        },
        "status": "reviewed_no_issue",
        "observed_at": "2026-08-30T14:00:00Z",
        "evidence": [
            {
                "evidence_id": "review-report",
                "kind": "manual_review",
                "ref": "evidence/safety-review.json",
                "sha256": "c" * 64,
            }
        ],
        "findings": [],
        "blocker": None,
        "blockers": [],
        "mutation_performed": False,
        "rights_decision_performed": False,
        "admission_performed": False,
    }


def test_safety_receipt_rejects_excessive_adapter_input_nesting() -> None:
    payload = _payload()
    nested: object = None
    for _ in range(102):
        nested = [nested]
    payload["adapter_input"] = nested

    with pytest.raises(ValidationError, match="maximum JSON nesting depth"):
        PackageSafetyEvidenceReceipt.model_validate(payload)


def test_safety_observed_at_rejects_non_rfc3339_offsets_at_all_boundaries() -> None:
    payload = _payload()
    payload["observed_at"] = "2026-08-30T14:00:00+0000"

    with pytest.raises(ValidationError, match="observed_at must be an RFC3339 string"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)
