"""Actual-artifact binding and freshness regressions, without provider execution."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError, model_serializer

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.pre_execution_safety import assess_pre_execution_safety
from skills_sdk.models.packaging import PackageReceiptV2
from skills_sdk.models.pre_execution_safety import CapabilitySafetyReview, PreExecutionSafetyEvidence
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.risk import SecurityFinding, SecurityScreeningResult
from skills_sdk.models.safety import PackageSafetyEvidenceReceipt
from tests.safety_execution_fixtures import synthetic_safety_evidence
from tests.test_provider_execution_contracts import _request

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


class _MaskedFinding(SecurityFinding):
    @model_serializer(mode="plain")
    def public_shape(self) -> dict[str, object]:
        return {
            "code": "synthetic_indicator",
            "category": "external_service",
            "severity": "warning",
            "message": "Synthetic fixture.",
            "evidence_refs": ["SKILL.md"],
        }


class _CallerEvidence(PreExecutionSafetyEvidence):
    @model_serializer(mode="plain")
    def serialization_must_not_run(self) -> dict[str, object]:
        raise AssertionError("caller evidence serializer must not run")


class _CallerChecklist(CapabilitySafetyReview):
    @model_serializer(mode="plain")
    def serialization_must_not_run(self) -> dict[str, object]:
        raise AssertionError("caller checklist serializer must not run")


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


def _rebind_review(request: ProviderExecutionRequest, payload: dict[str, object]) -> ProviderExecutionRequest:
    review = cast(dict[str, object], payload["safety_receipt"])
    normalized = PackageSafetyEvidenceReceipt.model_validate(review).model_dump(mode="json")
    return request.model_copy(update={"package_safety_receipt_sha256": canonical_json_sha256(normalized)})


def test_pipe_to_shell_in_non_script_requires_subprocess_review_and_recovers() -> None:
    request, evidence = _bound()
    payload = evidence.model_dump(mode="json")
    screening = cast(dict[str, object], payload["screening"])
    screening["status"] = "needs_review"
    screening["findings"] = [
        {
            "code": "pipe_to_shell_download",
            "category": "external_service",
            "severity": "warning",
            "message": "Synthetic shell invocation indicator.",
            "evidence_refs": ["SKILL.md"],
        }
    ]
    review = cast(dict[str, object], payload["safety_receipt"])
    for reference in cast(list[dict[str, object]], review["evidence"]):
        if reference["evidence_id"] == "static-screening":
            reference["sha256"] = canonical_json_sha256(screening)
    accepted_request = _rebind_review(request, payload)
    assert assess_pre_execution_safety(accepted_request, payload, checked_at=NOW) is None
    for check in cast(list[dict[str, object]], payload["checklist"]):
        if check["check_id"] == "filesystem_and_subprocess":
            check["status"] = "not_applicable"
    for reference in cast(list[dict[str, object]], review["evidence"]):
        if reference["evidence_id"] == "capability-checklist":
            reference["sha256"] = canonical_json_sha256(
                {"version": payload["checklist_version"], "checks": payload["checklist"]}
            )
    assert assess_pre_execution_safety(_rebind_review(request, payload), payload, checked_at=NOW) is not None
    assert assess_pre_execution_safety(request, evidence, checked_at=NOW) is None


@pytest.mark.parametrize("update", [{"category": "bogus"}, {"severity": "bogus"}, {"unknown": True}])
def test_models_deep_inside_raw_screening_mappings_must_be_revalidated(update: dict[str, object]) -> None:
    request, evidence = _bound()
    finding = SecurityFinding(
        code="synthetic_indicator",
        category="external_service",
        severity="warning",
        message="Synthetic fixture.",
        evidence_refs=("SKILL.md",),
    )
    forged = finding.model_copy(update=update)
    payload = evidence.model_dump(mode="json")
    screening = cast(dict[str, object], payload["screening"])
    screening.update(status="needs_review", findings=[forged])
    serialized = {
        **screening,
        "findings": [
            {
                **finding.model_dump(mode="json"),
                **{key: value for key, value in update.items() if key in SecurityFinding.model_fields},
            }
        ],
    }
    review = cast(dict[str, object], payload["safety_receipt"])
    for reference in cast(list[dict[str, object]], review["evidence"]):
        if reference["evidence_id"] == "static-screening":
            reference["sha256"] = canonical_json_sha256(serialized)
    assert assess_pre_execution_safety(_rebind_review(request, payload), payload, checked_at=NOW) is not None
    with pytest.raises(ValidationError):
        PreExecutionSafetyEvidence.model_validate(payload)
    assert assess_pre_execution_safety(request, evidence, checked_at=NOW) is None


@pytest.mark.parametrize("boundary", ["raw", "typed"])
@pytest.mark.parametrize("mutation", ["unknown", "bytes", "cycle", "numeric_flag"])
def test_nested_input_audit_precedes_serialization_and_recovers(boundary: str, mutation: str) -> None:
    request, evidence = _bound()
    changes: dict[str, object] = {"mutation_performed": 0}
    payload = evidence.model_dump(mode="json")
    serialized = cast(dict[str, object], payload["screening"]).copy()
    serialized["mutation_performed"] = 0
    if mutation != "numeric_flag":
        finding = SecurityFinding(
            code="synthetic_indicator",
            category="external_service",
            severity="warning",
            message="Synthetic fixture.",
            evidence_refs=("SKILL.md",),
        )
        cyclic: list[object] = []
        cyclic.append(cyclic)
        updates = {
            "unknown": {"unknown": True},
            "bytes": {"message": b"Synthetic fixture."},
            "cycle": {"evidence_refs": cyclic},
        }
        changes = {"status": "needs_review", "findings": [finding.model_copy(update=updates[mutation])]}
        serialized = {
            **cast(dict[str, object], payload["screening"]),
            "status": "needs_review",
            "findings": [finding.model_dump(mode="json")],
        }
    review = cast(dict[str, object], payload["safety_receipt"])
    for reference in cast(list[dict[str, object]], review["evidence"]):
        if reference["evidence_id"] == "static-screening":
            reference["sha256"] = canonical_json_sha256(serialized)
    changed_request = _rebind_review(request, payload)
    if boundary == "typed":
        supplied: object = evidence.model_copy(
            update={
                "screening": evidence.screening.model_copy(update=changes),
                "safety_receipt": PackageSafetyEvidenceReceipt.model_validate(review),
            }
        )
    else:
        cast(dict[str, object], payload["screening"]).update(changes)
        supplied = payload
    blocker = assess_pre_execution_safety(changed_request, supplied, checked_at=NOW)
    assert blocker is not None and blocker.code == "invalid_package_safety_evidence"
    with pytest.raises(ValidationError):
        PreExecutionSafetyEvidence.model_validate(supplied)
    assert assess_pre_execution_safety(request, evidence, checked_at=NOW) is None


@pytest.mark.parametrize("update", [{"unknown": True}, {"rationale": b"Synthetic fixture."}, {"check_id": "bogus"}])
def test_direct_copied_checklist_model_is_revalidated(update: dict[str, object]) -> None:
    _, evidence = _bound()
    check = evidence.checklist[0]
    with pytest.raises(ValidationError):
        CapabilitySafetyReview.model_validate(check.model_copy(update=update))
    assert CapabilitySafetyReview.model_validate(check) == check


@pytest.mark.parametrize("boundary", ["raw", "typed"])
@pytest.mark.parametrize("category", ["external_service", "bogus"])
def test_noncanonical_serializers_cannot_replace_raw_evidence(boundary: str, category: str) -> None:
    request, evidence = _bound()
    finding = _MaskedFinding.model_construct(
        code="synthetic_indicator",
        category=category,
        severity="warning",
        message="Synthetic fixture.",
        evidence_refs=("SKILL.md",),
    )
    payload = evidence.model_dump(mode="json")
    screening = cast(dict[str, object], payload["screening"])
    screening.update(status="needs_review", findings=[finding.public_shape()])
    review = cast(dict[str, object], payload["safety_receipt"])
    for reference in cast(list[dict[str, object]], review["evidence"]):
        if reference["evidence_id"] == "static-screening":
            reference["sha256"] = canonical_json_sha256(screening)
    changed_request = _rebind_review(request, payload)
    if boundary == "typed":
        supplied: object = evidence.model_copy(
            update={
                "screening": evidence.screening.model_copy(update={"status": "needs_review", "findings": (finding,)}),
                "safety_receipt": PackageSafetyEvidenceReceipt.model_validate(review),
            }
        )
    else:
        screening["findings"] = [finding]
        supplied = payload
    blocker = assess_pre_execution_safety(changed_request, supplied, checked_at=NOW)
    assert blocker is not None and blocker.code == "invalid_package_safety_evidence"
    with pytest.raises(ValidationError):
        PreExecutionSafetyEvidence.model_validate(supplied)
    assert assess_pre_execution_safety(request, evidence, checked_at=NOW) is None


def test_direct_evidence_subclass_rejects_before_type_conversion_and_recovers() -> None:
    request, evidence = _bound()
    supplied = _CallerEvidence.model_construct(**evidence.__dict__)
    with pytest.raises(ValidationError):
        PreExecutionSafetyEvidence.model_validate(supplied)
    blocker = assess_pre_execution_safety(request, supplied, checked_at=NOW)
    assert blocker is not None and blocker.code == "invalid_package_safety_evidence"
    assert PreExecutionSafetyEvidence.model_validate(evidence) == evidence


def test_direct_checklist_subclass_rejects_before_type_conversion_and_recovers() -> None:
    _, evidence = _bound()
    check = evidence.checklist[0]
    supplied = _CallerChecklist.model_construct(**check.__dict__)
    with pytest.raises(ValidationError):
        CapabilitySafetyReview.model_validate(supplied)
    assert CapabilitySafetyReview.model_validate(check) == check
