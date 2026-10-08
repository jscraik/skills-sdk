"""Actual-artifact binding and freshness regressions, without provider execution."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.pre_execution_safety import assess_pre_execution_safety
from skills_sdk.models.packaging import PackageReceiptV2
from skills_sdk.models.pre_execution_safety import PreExecutionSafetyEvidence
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.risk import SecurityScreeningResult
from skills_sdk.models.safety import PackageSafetyEvidenceReceipt
from tests.safety_execution_fixtures import synthetic_safety_evidence
from tests.test_provider_execution_contracts import _request

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


def _bound() -> tuple[ProviderExecutionRequest, PreExecutionSafetyEvidence]:
    path = Path(__file__).parent / "fixtures/package-receipts/accepted-v2.json"
    upstream = PackageReceiptV2.model_validate_json(path.read_text(encoding="utf-8"))
    assert upstream.candidate is not None
    assert upstream.manifest is not None
    screening = SecurityScreeningResult(
        candidate=upstream.candidate,
        sensor_ids=("sdk-static-signature-v1",),
        status="pass",
        scanned_paths=tuple(item.path for item in upstream.manifest.files),
    )
    evidence = synthetic_safety_evidence(upstream, screening, NOW)
    safety = evidence.safety_receipt
    payload = _request()
    payload.update(
        candidate=upstream.candidate.model_dump(mode="json"),
        package_safety_receipt_id=safety.receipt_id,
        package_safety_receipt_sha256=canonical_json_sha256(safety.model_dump(mode="json")),
    )
    return ProviderExecutionRequest.model_validate(payload), evidence


@pytest.mark.parametrize("boundary", ["typed", "raw", "json"])
def test_actual_bound_evidence_accepts_without_execution(boundary: str) -> None:
    request, evidence = _bound()
    supplied: object = evidence
    if boundary != "typed":
        supplied = evidence.model_dump(mode="json")
    if boundary == "json":
        supplied = json.loads(json.dumps(supplied))
    assert assess_pre_execution_safety(request, supplied, checked_at=NOW) is None


@pytest.mark.parametrize("field", ["input_receipt_id", "package_digest", "receipt_id", "candidate"])
def test_contradictory_actual_artifacts_block_and_recover(field: str) -> None:
    request, evidence = _bound()
    payload = evidence.model_dump(mode="json")
    review = cast(dict[str, object], payload["safety_receipt"])
    values = {"input_receipt_id": "other-receipt", "package_digest": "f" * 64, "receipt_id": "other-review"}
    if field == "candidate":
        candidate = cast(dict[str, object], review["candidate"])
        candidate["source_revision"] = "f" * 40
    else:
        review[field] = values[field]
    blocker = assess_pre_execution_safety(request, payload, checked_at=NOW)
    assert blocker is not None and blocker.code == "invalid_package_safety_evidence"
    assert assess_pre_execution_safety(request, evidence, checked_at=NOW) is None


@pytest.mark.parametrize("offset,expected", [(-3601, "stale"), (1, "future"), (-3600, None), (0, None)])
def test_review_clock_boundaries_and_corrected_recovery(offset: int, expected: str | None) -> None:
    request, evidence = _bound()
    payload = evidence.model_dump(mode="json")
    review = cast(dict[str, object], payload["safety_receipt"])
    review["observed_at"] = (NOW + timedelta(seconds=offset)).isoformat()
    normalized = PackageSafetyEvidenceReceipt.model_validate(review).model_dump(mode="json")
    changed_request = request.model_copy(update={"package_safety_receipt_sha256": canonical_json_sha256(normalized)})
    blocker = assess_pre_execution_safety(changed_request, payload, checked_at=NOW)
    if expected is None:
        assert blocker is None
    else:
        assert blocker is not None and blocker.code == f"package_safety_evidence_{expected}"
    assert assess_pre_execution_safety(request, evidence, checked_at=NOW) is None


def test_forged_nested_typed_artifact_is_revalidated() -> None:
    request, evidence = _bound()
    forged_review = evidence.safety_receipt.model_copy(update={"package_digest": "f" * 64})
    forged = evidence.model_copy(update={"safety_receipt": forged_review})
    assert assess_pre_execution_safety(request, forged, checked_at=NOW) is not None
    assert assess_pre_execution_safety(request, evidence, checked_at=NOW) is None


def test_packaged_schema_and_registry_reject_upstream_contradictions() -> None:
    _, evidence = _bound()
    registry = SchemaRegistry()
    payload = evidence.model_dump(mode="json")
    registry.validate("pre-execution-safety-evidence.v1", payload)
    review = cast(dict[str, object], payload["safety_receipt"])
    review["input_receipt_id"] = "other-upstream"
    with pytest.raises(ValidationError):
        PreExecutionSafetyEvidence.model_validate(payload)
    with pytest.raises(ContractError):
        registry.validate("pre-execution-safety-evidence.v1", payload)
    registry.validate("pre-execution-safety-evidence.v1", evidence.model_dump(mode="json"))


@pytest.mark.parametrize("field", ["schema_version", "safe"])
def test_evidence_schema_rejects_unknown_or_changed_contract(field: str) -> None:
    _, evidence = _bound()
    payload = evidence.model_dump(mode="json")
    payload[field] = "pre-execution-safety-evidence/v2" if field == "schema_version" else True
    with pytest.raises(ContractError):
        SchemaRegistry().validate("pre-execution-safety-evidence.v1", payload)


@pytest.mark.parametrize("max_age", [True, 0, -1, 86401, "3600"])
def test_freshness_policy_does_not_coerce_invalid_values(max_age: object) -> None:
    request, evidence = _bound()
    blocker = assess_pre_execution_safety(request, evidence, checked_at=NOW, max_age_seconds=cast(int, max_age))
    assert blocker is not None and blocker.code == "invalid_safety_freshness_policy"


def test_missing_unknown_and_metadata_only_evidence_block() -> None:
    request, evidence = _bound()
    assert assess_pre_execution_safety(request, None, checked_at=NOW) is not None
    unknown = evidence.model_dump(mode="json")
    unknown["safe"] = True
    assert assess_pre_execution_safety(request, unknown, checked_at=NOW) is not None
    metadata = deepcopy(evidence.model_dump(mode="json"))
    review = cast(dict[str, object], metadata["safety_receipt"])
    cast(dict[str, object], review["reviewer"])["method"] = "metadata"
    changed_request = request.model_copy(update={"package_safety_receipt_sha256": canonical_json_sha256(review)})
    blocker = assess_pre_execution_safety(changed_request, metadata, checked_at=NOW)
    assert blocker is not None and blocker.code == "package_safety_review_required"
    assert assess_pre_execution_safety(request, evidence, checked_at=NOW) is None


def test_review_cannot_predate_its_upstream_build() -> None:
    request, evidence = _bound()
    payload = evidence.model_dump(mode="json")
    review = cast(dict[str, object], payload["safety_receipt"])
    review["observed_at"] = (evidence.package_receipt.finished_at - timedelta(seconds=1)).isoformat()
    normalized = PackageSafetyEvidenceReceipt.model_validate(review).model_dump(mode="json")
    changed_request = request.model_copy(update={"package_safety_receipt_sha256": canonical_json_sha256(normalized)})
    blocker = assess_pre_execution_safety(changed_request, payload, checked_at=NOW)
    assert blocker is not None and blocker.code == "package_safety_evidence_predates_build"
    assert assess_pre_execution_safety(request, evidence, checked_at=NOW) is None
