"""Bind supplied semantic review dispositions to one safely captured candidate."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from skills_sdk.models.content_review import ContentReviewAssessment, ContentReviewResult
from skills_sdk.models.validation import SkillPackageFinding, ValidationSeverity
from skills_sdk.validation.skill_package import validate_skill_package


def _finding(code: str, message: str) -> SkillPackageFinding:
    return SkillPackageFinding(code=code, severity=ValidationSeverity.BLOCKER, message=message)


def assess_content_review(package_root: Path, *, source_revision: str, assessment: object) -> ContentReviewResult:
    """Verify supplied evidence coverage; never run a reviewer or external lookup."""
    validation = validate_skill_package(package_root, source_revision=source_revision)
    findings = list(validation.findings)
    review: ContentReviewAssessment | None = None
    try:
        if isinstance(assessment, ContentReviewAssessment) and type(assessment) is not ContentReviewAssessment:
            raise ValueError("supplied typed review must use the canonical assessment model")
        raw = (
            assessment.model_dump(mode="python", warnings="error")
            if isinstance(assessment, ContentReviewAssessment)
            else assessment
        )
        review = ContentReviewAssessment.model_validate(raw)
    except (ValidationError, ValueError, TypeError, RuntimeError, LookupError, PydanticSerializationError):
        findings.append(_finding("invalid_content_review", "supplied review must match the closed assessment contract"))
    if validation.status == "pass" and review is not None:
        if review.candidate != validation.candidate:
            findings.append(_finding("content_review_candidate_mismatch", "review must bind the current candidate"))
        files = {item.path: item.sha256 for item in validation.files}
        expected = {path for path in files if path.startswith("references/")}
        reviewed = {item.path for item in review.items if item.dimension == "reference"}
        if reviewed != expected:
            findings.append(_finding("content_review_coverage_gap", "review every actual reference exactly once"))
        if any(files.get(item.ref) != item.sha256 for item in review.evidence):
            findings.append(
                _finding("content_review_evidence_mismatch", "review evidence must match captured package files")
            )
        if any(item.status != "clear" for item in review.items):
            findings.append(_finding("content_review_unresolved", "review findings and owned gaps require correction"))
    return ContentReviewResult(
        candidate=validation.candidate,
        status="blocked" if findings else "pass",
        assessment=review,
        findings=tuple(findings),
    )


__all__ = ["assess_content_review"]
