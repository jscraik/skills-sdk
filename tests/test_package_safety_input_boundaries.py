"""Direct-input boundary regressions for package safety evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceipt, PackageReceiptV2
from skills_sdk.models.safety import (
    PackageSafetyEvidenceReceipt,
    PackageSafetyEvidenceReference,
    PackageSafetyReviewer,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "package-receipts"


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


@pytest.mark.parametrize("value", ['{"token":"opaque-value"}', "{'password':'opaque-value'}"])
def test_safety_rejects_quoted_credential_keys_at_all_boundaries(value: str) -> None:
    payload = _payload()
    payload["status"] = "issue_found"
    payload["findings"] = [
        {
            "code": "unsafe_operation",
            "category": "unsafe_operation",
            "severity": "blocker",
            "message": f"declared credential-shaped input {value}",
            "evidence_ids": ["review-report"],
        }
    ]
    blocker = {
        "code": "issue_found",
        "message": "package safety issue found",
        "evidence_refs": ["evidence/safety-review.json"],
    }
    payload["blocker"] = blocker
    payload["blockers"] = [blocker]

    with pytest.raises(ValidationError, match="credential-shaped"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_safety_rejects_control_whitespace_credential_keys_at_all_boundaries() -> None:
    payload = _payload()
    payload["status"] = "issue_found"
    payload["findings"] = [
        {
            "code": "unsafe_operation",
            "category": "unsafe_operation",
            "severity": "blocker",
            "message": "declared token\x1c=opaque-value",
            "evidence_ids": ["review-report"],
        }
    ]
    blocker = {
        "code": "issue_found",
        "message": "package safety issue found",
        "evidence_refs": ["evidence/safety-review.json"],
    }
    payload["blocker"] = blocker
    payload["blockers"] = [blocker]

    with pytest.raises(ValidationError, match="credential-shaped"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_safety_rejects_generator_carried_bytes_at_direct_model_boundary() -> None:
    payload = _payload()
    payload["status"] = "issue_found"
    payload["findings"] = [
        {
            "code": "unsafe_operation",
            "category": "unsafe_operation",
            "severity": "blocker",
            "message": "declared operation requires review",
            "evidence_ids": (value for value in [b"review-report"]),
        }
    ]
    blocker = {
        "code": "issue_found",
        "message": "package safety issue found",
        "evidence_refs": ["evidence/safety-review.json"],
    }
    payload["blocker"] = blocker
    payload["blockers"] = [blocker]

    with pytest.raises(ValidationError, match="JSON-compatible containers"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="invalid_json_value"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_safety_accepts_nested_exported_contract_models() -> None:
    payload = _payload()
    payload["candidate"] = PackageCandidateIdentity.model_validate(payload["candidate"])
    payload["reviewer"] = PackageSafetyReviewer.model_validate(payload["reviewer"])
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    payload["evidence"] = tuple(PackageSafetyEvidenceReference.model_validate(item) for item in evidence)

    receipt = PackageSafetyEvidenceReceipt.model_validate(payload)

    assert receipt.candidate.package_id == "synthetic-skill"


def test_safety_rejects_whitespace_candidate_identity_before_upstream_binding() -> None:
    upstream = PackageReceiptV2.model_validate(
        json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))
    )
    assert upstream.candidate is not None
    assert upstream.package_digest is not None
    payload = _payload()
    payload["candidate"] = upstream.candidate.model_dump(mode="json")
    candidate = payload["candidate"]
    assert isinstance(candidate, dict)
    candidate["package_id"] = f" {upstream.candidate.package_id} "
    payload["input_receipt_id"] = upstream.receipt_id
    payload["package_digest"] = upstream.package_digest

    with pytest.raises(ValidationError, match="candidate identity fields must already be normalized"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_safety_rejects_historical_v1_upstream_receipt_binding() -> None:
    upstream_receipt = PackageReceipt.model_validate(
        json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    )
    assert upstream_receipt.candidate is not None
    assert upstream_receipt.package_digest is not None
    payload = _payload()
    payload["candidate"] = upstream_receipt.candidate.model_dump(mode="json")
    payload["input_receipt_id"] = upstream_receipt.receipt_id
    payload["package_digest"] = upstream_receipt.package_digest
    safety_receipt = PackageSafetyEvidenceReceipt.model_validate(payload)

    with pytest.raises(ValueError, match="built v2 upstream package receipt"):
        safety_receipt.validate_against_package_receipt(cast(PackageReceiptV2, upstream_receipt))
    with pytest.raises(ContractError, match="upstream package receipt binding"):
        SchemaRegistry().validate_package_safety_evidence_against_package_receipt(payload, upstream_receipt)
