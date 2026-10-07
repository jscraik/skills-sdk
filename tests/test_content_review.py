"""Supplied review evidence: accepted, rejected and corrected package inputs."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import UserDict, deque
from collections.abc import Callable, Iterable
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar

import pytest
from pydantic import ValidationError

from skills_sdk.cli import main as main_module
from skills_sdk.cli.main import main
from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.content_review import ContentReviewAssessment, ContentReviewExecutionResult, ContentReviewResult
from skills_sdk.models.validation import SkillPackageFinding, ValidationSeverity
from skills_sdk.validation.content_review import assess_content_review
from skills_sdk.validation.skill_package import validate_skill_package

REVISION = "1" * 40


@pytest.mark.parametrize("container", [UserDict, MappingProxyType])
@pytest.mark.parametrize(
    "section,field", [("candidate", "package_id"), ("reviewer", "adapter_id"), ("evidence", "ref")]
)
def test_mapping_byte_text_rejects_and_recovers(tmp_path: Path, container: Callable, section: str, field: str) -> None:
    root, data = _fixture(tmp_path)
    malformed = deepcopy(data)
    values = malformed[section][0] if section == "evidence" else malformed[section]
    wrapped = container({**values, field: values[field].encode()})
    if section == "evidence":
        malformed[section][0] = wrapped
    else:
        malformed[section] = wrapped
    with pytest.raises(ValidationError):
        ContentReviewAssessment.model_validate(malformed)
    rejected = assess_content_review(root, source_revision=REVISION, assessment=malformed)
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    corrected = deepcopy(data)
    if section == "evidence":
        corrected[section][0] = container(values)
    else:
        corrected[section] = container(data[section])
    assert assess_content_review(root, source_revision=REVISION, assessment=corrected).status == "pass"


@pytest.mark.parametrize("model", [ContentReviewResult, ContentReviewExecutionResult])
@pytest.mark.parametrize("update", [{"code": "INVALID"}, {"evidence_refs": ("../escape",)}])
def test_forged_finding_rejects_and_recovers(model: type[ContentReviewResult], update: dict[str, object]) -> None:
    finding = SkillPackageFinding(
        code="fixture_blocked", severity=ValidationSeverity.BLOCKER, message="Blocked fixture"
    )
    payload = {"candidate": None, "status": "blocked", "findings": (finding.model_copy(update=update),)}
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    assert model.model_validate({**payload, "findings": (finding,)}).status == "blocked"


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "review-fixture"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-fixture\ndescription: Review supplied examples.\n---\n# Review\n")
    (root / "references").mkdir()
    (root / "references/guide.md").write_text("# Supplied example review\nUse the supplied fixture only.\n")
    validation = validate_skill_package(root, source_revision=REVISION)
    assert validation.candidate is not None
    data: dict[str, object] = {
        "candidate": validation.candidate.model_dump(mode="json"),
        "reviewer": {"adapter_id": "fixture-review", "adapter_version_or_digest": "1", "method": "manual_review"},
        "evidence": [
            {
                "evidence_id": "entry" if item.path == "SKILL.md" else "guide",
                "kind": "manual_review",
                "ref": item.path,
                "sha256": item.sha256,
            }
            for item in validation.files
        ],
        "items": [
            {
                "dimension": dimension,
                "path": path,
                "status": "clear",
                "rationale": "Fixture review recorded.",
                "evidence_ids": ["entry" if path == "SKILL.md" else "guide"],
            }
            for dimension, path in (
                ("description", "SKILL.md"),
                ("progressive_disclosure", "SKILL.md"),
                ("reference", "references/guide.md"),
            )
        ],
    }
    return root, data


@pytest.mark.parametrize("field", ["rationale", "owner", "path"])
def test_byte_string_review_input_rejects_and_recovers(tmp_path: Path, field: str) -> None:
    root, data = _fixture(tmp_path)
    malformed = deepcopy(data)
    value = malformed["items"][0].get(field) or "fixture-owner"
    malformed["items"][0][field] = value.encode()
    with pytest.raises(ValidationError):
        ContentReviewAssessment.model_validate(malformed)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("content-review-assessment.v1", malformed)
    rejected = assess_content_review(root, source_revision=REVISION, assessment=malformed)
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    assert assess_content_review(root, source_revision=REVISION, assessment=data).status == "pass"


@pytest.mark.parametrize(
    "section,field", [("candidate", "package_id"), ("reviewer", "adapter_id"), ("evidence", "ref")]
)
def test_nested_byte_text_rejects_before_coercion(tmp_path: Path, section: str, field: str) -> None:
    root, data = _fixture(tmp_path)
    malformed = deepcopy(data)
    target = malformed[section][0] if section == "evidence" else malformed[section]
    target[field] = target[field].encode()
    with pytest.raises(ValidationError):
        ContentReviewAssessment.model_validate(malformed)
    assert assess_content_review(root, source_revision=REVISION, assessment=malformed).status == "blocked"
    assert assess_content_review(root, source_revision=REVISION, assessment=data).status == "pass"


def test_forged_typed_byte_text_is_not_laundered_by_service(tmp_path: Path) -> None:
    root, data = _fixture(tmp_path)
    assessment = ContentReviewAssessment.model_validate(data)
    forged_item = assessment.items[0].model_copy(update={"rationale": b"Fixture review recorded."})
    forged = assessment.model_copy(update={"items": (forged_item, *assessment.items[1:])})
    assert assess_content_review(root, source_revision=REVISION, assessment=forged).status == "blocked"
    assert assess_content_review(root, source_revision=REVISION, assessment=assessment).status == "pass"


def test_generator_evidence_rejects_forged_instances_and_recovers(tmp_path: Path) -> None:
    root, data = _fixture(tmp_path)
    assessment = ContentReviewAssessment.model_validate(data)
    forged = assessment.evidence[0].model_copy(update={"sha256": "invalid"})
    malformed = {**data, "evidence": (item for item in (forged, *assessment.evidence[1:]))}
    with pytest.raises(ValidationError):
        ContentReviewAssessment.model_validate(malformed)
    malformed["evidence"] = (item for item in (forged, *assessment.evidence[1:]))
    rejected = assess_content_review(root, source_revision=REVISION, assessment=malformed)
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    for evidence in (list(assessment.evidence), assessment.evidence):
        assert (
            assess_content_review(root, source_revision=REVISION, assessment={**data, "evidence": evidence}).status
            == "pass"
        )


@pytest.mark.parametrize("item_index", [0, 1, 2])
def test_completed_disposition_requires_its_own_source_evidence(tmp_path: Path, item_index: int) -> None:
    root, data = _fixture(tmp_path)
    malformed = deepcopy(data)
    malformed["items"][item_index]["evidence_ids"] = ["guide" if item_index < 2 else "entry"]
    if item_index == 2:
        malformed["evidence"] = malformed["evidence"][:1]
    with pytest.raises(ValidationError):
        ContentReviewAssessment.model_validate(malformed)
    with pytest.raises(ValidationError):
        ContentReviewAssessment.model_validate_json(json.dumps(malformed))
    with pytest.raises(ContractError):
        SchemaRegistry().validate("content-review-assessment.v1", malformed)
    rejected = assess_content_review(root, source_revision=REVISION, assessment=malformed)
    assert rejected.status == "blocked"
    assert rejected.findings[0].code == "invalid_content_review"
    SchemaRegistry().validate("content-review-assessment.v1", data)
    assert assess_content_review(root, source_revision=REVISION, assessment=data).status == "pass"


def test_forged_disposition_cannot_borrow_other_file_evidence(tmp_path: Path) -> None:
    root, data = _fixture(tmp_path)
    review = ContentReviewAssessment.model_validate(data)
    forged_reference = review.items[2].model_copy(update={"evidence_ids": ("entry",)})
    forged = review.model_copy(update={"items": (*review.items[:2], forged_reference), "evidence": review.evidence[:1]})
    rejected = assess_content_review(root, source_revision=REVISION, assessment=forged)
    assert rejected.status == "blocked"
    assert rejected.findings[0].code == "invalid_content_review"
    assert assess_content_review(root, source_revision=REVISION, assessment=review).status == "pass"


def test_review_missing_reference_then_corrected_input(tmp_path: Path) -> None:
    root, data = _fixture(tmp_path)
    review = ContentReviewAssessment.model_validate(data)
    missing = review.model_copy(update={"items": review.items[:2], "evidence": review.evidence[:1]})
    before = (root / "SKILL.md").read_bytes()
    rejected = assess_content_review(root, source_revision=REVISION, assessment=missing)
    assert rejected.status == "blocked"
    assert rejected.findings[0].code == "content_review_coverage_gap"
    accepted = assess_content_review(root, source_revision=REVISION, assessment=review)
    assert accepted.status == "pass"
    assert accepted.semantic_review_executed is False
    assert accepted.promotion_authorized is False
    SchemaRegistry().validate("content-review.v1", accepted.model_dump(mode="json"))
    SchemaRegistry().validate("content-review-assessment.v1", review.model_dump(mode="json"))
    assert (root / "SKILL.md").read_bytes() == before


@pytest.mark.parametrize("field,value", [("status", "finding"), ("status", "gap")])
def test_unresolved_review_blocks_until_disposition_is_corrected(tmp_path: Path, field: str, value: str) -> None:
    root, data = _fixture(tmp_path)
    review = ContentReviewAssessment.model_validate(data)
    item = review.items[0].model_copy(update={field: value, "owner": "fixture-owner"})
    changed = review.model_copy(update={"items": (item, *review.items[1:])})
    rejected = assess_content_review(root, source_revision=REVISION, assessment=changed)
    assert rejected.status == "blocked"
    assert any(finding.code == "content_review_unresolved" for finding in rejected.findings)
    assert assess_content_review(root, source_revision=REVISION, assessment=review).status == "pass"


def test_stale_candidate_and_wrong_evidence_digest_block(tmp_path: Path) -> None:
    root, data = _fixture(tmp_path)
    review = ContentReviewAssessment.model_validate(data)
    wrong = review.evidence[0].model_copy(update={"sha256": "0" * 64})
    result = assess_content_review(
        root, source_revision=REVISION, assessment=review.model_copy(update={"evidence": (wrong, *review.evidence[1:])})
    )
    assert result.findings[0].code == "content_review_evidence_mismatch"
    (root / "references/guide.md").write_text("# Changed guide\n")
    stale = assess_content_review(root, source_revision=REVISION, assessment=review)
    assert any(item.code == "content_review_candidate_mismatch" for item in stale.findings)


@pytest.mark.parametrize("assessment", [None, {}, {"unexpected": True}])
def test_malformed_review_is_a_typed_blocker(tmp_path: Path, assessment: object) -> None:
    root, _data = _fixture(tmp_path)
    result = assess_content_review(root, source_revision=REVISION, assessment=assessment)
    assert result.status == "blocked"
    assert result.findings[0].code == "invalid_content_review"


@pytest.mark.parametrize(
    ("field", "value"),
    [("path", "../private"), ("status", "approved"), ("evidence_ids", ("unknown",)), ("rationale", "")],
)
def test_forged_nested_review_blocks_then_recovers(tmp_path: Path, field: str, value: object) -> None:
    root, data = _fixture(tmp_path)
    review = ContentReviewAssessment.model_validate(data)
    forged_item = review.items[0].model_copy(update={field: value})
    forged = review.model_copy(update={"items": (forged_item, *review.items[1:])})
    rejected = assess_content_review(root, source_revision=REVISION, assessment=forged)
    assert rejected.status == "blocked"
    assert rejected.findings[0].code == "invalid_content_review"
    assert assess_content_review(root, source_revision=REVISION, assessment=review).status == "pass"


@pytest.mark.parametrize("json_output", [False, True])
def test_cli_rejection_and_corrected_input(tmp_path: Path, json_output: bool) -> None:
    root, data = _fixture(tmp_path)
    assessment = tmp_path / "assessment.json"
    assessment.write_text("{}")
    command = [
        sys.executable,
        "-m",
        "skills_sdk.cli.main",
        "review-content",
        str(root),
        "--source-revision",
        REVISION,
        "--assessment",
        str(assessment),
    ]
    if json_output:
        command.append("--json")
    rejected = subprocess.run(command, capture_output=True, text=True, check=False)
    assert rejected.returncode == 2
    assert "Traceback" not in rejected.stderr
    if json_output:
        assert json.loads(rejected.stdout)["findings"][0]["code"] == "invalid_content_review"
    else:
        assert rejected.stdout.startswith("review-content: blocked (")
        assert "invalid_content_review" in rejected.stdout
    assessment.write_text(json.dumps(data))
    accepted = subprocess.run(command, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0
    assert "Traceback" not in accepted.stderr
    if json_output:
        assert json.loads(accepted.stdout)["status"] == "pass"
    else:
        assert accepted.stdout.startswith("review-content: pass (")


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("capability", ["O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK", "supports_dir_fd"])
def test_cli_unsupported_assessment_read_is_a_typed_blocker(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    json_output: bool,
    capability: str,
) -> None:
    root, data = _fixture(tmp_path)
    assessment = tmp_path / "assessment.json"
    assessment.write_text(json.dumps(data))
    monkeypatch.setattr(main_module.os, capability, set() if capability == "supports_dir_fd" else 0)
    command = ["review-content", str(root), "--source-revision", REVISION, "--assessment", str(assessment)]
    if json_output:
        command.append("--json")
    assert main(command) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    if json_output:
        blocker = json.loads(captured.out)
        assert blocker["code"] == "unsupported_context_read"
        assert blocker["evidence_refs"] == ["docs/compatibility.md"]
        SchemaRegistry().validate("blocker.v1", blocker)
    else:
        assert captured.out.startswith("review-content: blocked\n")
        assert "unsupported_context_read" in captured.out

    monkeypatch.undo()
    assert main(command) == 0
    recovered = capsys.readouterr()
    assert recovered.err == ""
    if json_output:
        result = json.loads(recovered.out)
        assert result["status"] == "pass"
        SchemaRegistry().validate("content-review.v1", result)
    else:
        assert recovered.out.startswith("review-content: pass (")


@pytest.mark.parametrize("payload", [None, b"{", b"\xff", b'{"items": [], "items": []}', b"[" * 10_000 + b"]" * 10_000])
def test_cli_other_assessment_read_errors_remain_invalid_reviews(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: bytes | None
) -> None:
    root, _data = _fixture(tmp_path)
    assessment = tmp_path / "assessment.json"
    if payload is not None:
        assessment.write_bytes(payload)
    command = ["review-content", str(root), "--source-revision", REVISION, "--assessment", str(assessment), "--json"]
    assert main(command) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    assert result["status"] == "blocked"
    assert result["findings"][0]["code"] == "invalid_content_review"
    SchemaRegistry().validate("content-review.v1", result)


@pytest.mark.parametrize(
    ("field", "update"),
    [
        ("reviewer", {"method": "invalid"}),
        ("reviewer", {"adapter_id": "api_key=private"}),
        ("evidence", {"sha256": "invalid"}),
        ("evidence", {"ref": "../escape"}),
    ],
)
def test_nested_forged_models_reject_and_recover(tmp_path: Path, field: str, update: dict[str, str]) -> None:
    root, data = _fixture(tmp_path)
    original = ContentReviewAssessment.model_validate(data)
    malformed = dict(data)
    if field == "reviewer":
        malformed[field] = original.reviewer.model_copy(update=update)
    else:
        malformed[field] = (original.evidence[0].model_copy(update=update), *original.evidence[1:])
    with pytest.raises(ValidationError):
        ContentReviewAssessment.model_validate(malformed)
    rejected = assess_content_review(root, source_revision=REVISION, assessment=malformed)
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    assert assess_content_review(root, source_revision=REVISION, assessment=original).status == "pass"


@pytest.mark.parametrize("container", [iter, deque, set, frozenset])
def test_evidence_rejects_other_iterables_before_consuming_them(
    tmp_path: Path, container: Callable[[Iterable[object]], Iterable[object]]
) -> None:
    _root, data = _fixture(tmp_path)
    original = ContentReviewAssessment.model_validate(data)
    evidence = container(original.evidence)
    with pytest.raises(ValidationError, match="review evidence must be a list or tuple"):
        ContentReviewAssessment.model_validate({**data, "evidence": evidence})
    assert set(evidence) == set(original.evidence)


@pytest.mark.parametrize("container", [list, tuple])
def test_evidence_sequences_preserve_conversion_and_revalidation(
    tmp_path: Path, container: Callable[[Iterable[object]], Iterable[object]]
) -> None:
    _root, data = _fixture(tmp_path)
    original = ContentReviewAssessment.model_validate(data)
    for evidence in (data["evidence"], original.evidence):
        assert ContentReviewAssessment.model_validate({**data, "evidence": container(evidence)}) == original
    for digest in ("invalid", 123):
        forged = original.evidence[0].model_copy(update={"sha256": digest})
        with pytest.raises(ValidationError):
            ContentReviewAssessment.model_validate({**data, "evidence": container((forged, *original.evidence[1:]))})


def _blocked_payload() -> dict[str, object]:
    finding = SkillPackageFinding(
        code="fixture_blocked", severity=ValidationSeverity.BLOCKER, message="Blocked fixture"
    )
    return {"candidate": None, "status": "blocked", "findings": [finding.model_dump(mode="json")]}


@pytest.mark.parametrize("value", [0, 1, "false", "true", b"false", None])
@pytest.mark.parametrize(
    ("model", "schema", "field"),
    [
        (ContentReviewResult, "content-review.v1", "semantic_review_executed"),
        (ContentReviewResult, "content-review.v1", "promotion_authorized"),
        (ContentReviewResult, "content-review.v1", "network_used"),
        (ContentReviewResult, "content-review.v1", "mutation_performed"),
        (ContentReviewExecutionResult, "content-review-execution.v1", "promotion_authorized"),
        (ContentReviewExecutionResult, "content-review-execution.v1", "adapter_invoked"),
    ],
)
def test_proof_flags_require_exact_booleans(
    value: object, model: type[ContentReviewResult] | type[ContentReviewExecutionResult], schema: str, field: str
) -> None:
    payload = {**_blocked_payload(), field: value}
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate(schema, payload)
    corrected = {**payload, field: False}
    model.model_validate(corrected)
    SchemaRegistry().validate(schema, corrected)


@pytest.mark.parametrize("missing", ["candidate", "reviewer", "both"])
def test_invocation_claim_requires_candidate_and_reviewer(tmp_path: Path, missing: str) -> None:
    _root, data = _fixture(tmp_path)
    payload = {
        **_blocked_payload(),
        "adapter_invoked": True,
        "candidate": data["candidate"],
        "reviewer": data["reviewer"],
    }
    corrected = dict(payload)
    for field in ("candidate", "reviewer") if missing == "both" else (missing,):
        payload[field] = None
    with pytest.raises(ValidationError):
        ContentReviewExecutionResult.model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("content-review-execution.v1", payload)
    ContentReviewExecutionResult.model_validate(corrected)
    SchemaRegistry().validate("content-review-execution.v1", corrected)


def test_returned_review_requires_observed_invocation(tmp_path: Path) -> None:
    root, data = _fixture(tmp_path)
    review = assess_content_review(root, source_revision=REVISION, assessment=data)
    payload = {
        **_blocked_payload(),
        "candidate": data["candidate"],
        "reviewer": data["reviewer"],
        "review": review.model_dump(mode="json"),
        "assessment_sha256": canonical_json_sha256(review.assessment.model_dump(mode="json")),
        "adapter_invoked": False,
    }
    with pytest.raises(ValidationError):
        ContentReviewExecutionResult.model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("content-review-execution.v1", payload)
    corrected = {**payload, "adapter_invoked": True}
    ContentReviewExecutionResult.model_validate(corrected)
    SchemaRegistry().validate("content-review-execution.v1", corrected)


def test_streaming_items_are_rejected_without_consumption(tmp_path: Path) -> None:
    root, data = _fixture(tmp_path)
    items = iter(data["items"])
    with pytest.raises(ValidationError):
        ContentReviewAssessment.model_validate({**data, "items": items})
    assert list(items) == data["items"]
    items = iter(data["items"])
    rejected = assess_content_review(root, source_revision=REVISION, assessment={**data, "items": items})
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    assert list(items) == data["items"]
    assert assess_content_review(root, source_revision=REVISION, assessment=data).status == "pass"


@pytest.mark.parametrize(
    "model,schema",
    [(ContentReviewResult, "content-review.v1"), (ContentReviewExecutionResult, "content-review-execution.v1")],
)
def test_warning_only_blocked_result_requires_actual_blocker(
    model: type[ContentReviewResult] | type[ContentReviewExecutionResult], schema: str
) -> None:
    payload = _blocked_payload()
    payload["findings"][0]["severity"] = "warning"
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate(schema, payload)
    payload["findings"][0]["severity"] = "blocker"
    model.model_validate(payload)
    SchemaRegistry().validate(schema, payload)


def test_streaming_findings_and_evidence_ids_are_not_consumed(tmp_path: Path) -> None:
    _root, data = _fixture(tmp_path)
    item = ContentReviewAssessment.model_validate(data).items[0]
    evidence_ids = iter(item.evidence_ids)
    with pytest.raises(ValidationError):
        type(item).model_validate({**item.model_dump(mode="json"), "evidence_ids": evidence_ids})
    assert tuple(evidence_ids) == item.evidence_ids
    findings = _blocked_payload()["findings"]
    iterator = iter(findings)
    with pytest.raises(ValidationError):
        ContentReviewResult.model_validate({**_blocked_payload(), "findings": iterator})
    assert list(iterator) == findings


class FailingAssessmentSerializer(ContentReviewAssessment):
    dump_error: ClassVar[type[Exception]] = RuntimeError

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        raise self.dump_error("private serializer diagnostic")


@pytest.mark.parametrize("error", [RuntimeError, KeyError])
def test_typed_serializer_failure_is_redacted_and_recovers(tmp_path: Path, error: type[Exception]) -> None:
    root, data = _fixture(tmp_path)
    FailingAssessmentSerializer.dump_error = error
    malformed = FailingAssessmentSerializer.model_validate(data)
    rejected = assess_content_review(root, source_revision=REVISION, assessment=malformed)
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    assert "private serializer" not in rejected.model_dump_json()
    assert assess_content_review(root, source_revision=REVISION, assessment=data).status == "pass"
