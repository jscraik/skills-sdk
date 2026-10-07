"""Supplied review evidence: accepted, rejected and corrected package inputs."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.cli import main as main_module
from skills_sdk.cli.main import main
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.content_review import ContentReviewAssessment
from skills_sdk.validation.content_review import assess_content_review
from skills_sdk.validation.skill_package import validate_skill_package

REVISION = "1" * 40


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
