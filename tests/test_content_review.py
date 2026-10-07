"""Supplied review evidence: accepted, rejected and corrected package inputs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

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
            {"evidence_id": "entry", "kind": "manual_review", "ref": item.path, "sha256": item.sha256}
            for item in validation.files
            if item.path == "SKILL.md"
        ],
        "items": [
            {
                "dimension": dimension,
                "path": path,
                "status": "clear",
                "rationale": "Fixture review recorded.",
                "evidence_ids": ["entry"],
            }
            for dimension, path in (
                ("description", "SKILL.md"),
                ("progressive_disclosure", "SKILL.md"),
                ("reference", "references/guide.md"),
            )
        ],
    }
    return root, data


def test_review_missing_reference_then_corrected_input(tmp_path: Path) -> None:
    root, data = _fixture(tmp_path)
    review = ContentReviewAssessment.model_validate(data)
    missing = review.model_copy(update={"items": review.items[:2]})
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
        root, source_revision=REVISION, assessment=review.model_copy(update={"evidence": (wrong,)})
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


def test_cli_rejection_and_corrected_input(tmp_path: Path) -> None:
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
        "--json",
    ]
    rejected = subprocess.run(command, capture_output=True, text=True, check=False)
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["findings"][0]["code"] == "invalid_content_review"
    assessment.write_text(json.dumps(data))
    accepted = subprocess.run(command, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0
    assert json.loads(accepted.stdout)["status"] == "pass"
