"""Candidate-bound, supplied description and reference review evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticSerializationError

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.safety import (
    PackageSafetyEvidenceReference,
    PackageSafetyReviewer,
    SafetyEvidenceId,
    _public_text_is_redaction_safe,
)
from skills_sdk.models.validation import SkillPackageFinding


class _ReviewModel(_ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    @field_validator(
        "semantic_review_executed",
        "promotion_authorized",
        "network_used",
        "mutation_performed",
        "adapter_invoked",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def proof_flags_are_exact_booleans(cls, value: object) -> bool:
        if type(value) is not bool:
            raise ValueError("review proof flags require exact booleans")
        return value

    @field_validator("reviewer", mode="before", check_fields=False)
    @classmethod
    def nested_reviewer_is_revalidated(cls, value: object) -> object:
        if isinstance(value, PackageSafetyReviewer):
            try:
                return value.model_dump(mode="python", warnings="error")
            except PydanticSerializationError:
                raise ValueError("reviewer failed revalidation") from None
        return value


class ContentReviewItem(_ReviewModel):
    """One review disposition, not an SDK-generated semantic judgement."""

    dimension: Literal["description", "progressive_disclosure", "reference"]
    path: PortablePath
    status: Literal["clear", "finding", "gap"]
    rationale: NonEmptyText
    evidence_ids: tuple[SafetyEvidenceId, ...] = ()
    owner: NonEmptyText | None = None

    @field_validator("path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        require_portable_relative_path(value)
        if not _public_text_is_redaction_safe(value):
            raise ValueError("review paths must be redaction-safe")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _public_text_is_redaction_safe(value) for value in values):
            raise ValueError("review evidence ids must be redaction-safe")
        return values

    @field_validator("rationale", "owner")
    @classmethod
    def public_text_is_safe(cls, value: str | None) -> str | None:
        if value is not None and not _public_text_is_redaction_safe(value):
            raise ValueError("review text must be redaction-safe")
        return value

    @model_validator(mode="after")
    def disposition_has_evidence_or_owner(self) -> ContentReviewItem:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("review evidence ids must be unique")
        if self.status == "gap":
            if self.owner is None:
                raise ValueError("review gaps require an owner")
        elif not self.evidence_ids:
            raise ValueError("completed review dispositions require evidence")
        if self.dimension != "reference" and self.path != "SKILL.md":
            raise ValueError("entrypoint review dimensions target SKILL.md")
        if self.dimension == "reference" and not self.path.startswith("references/"):
            raise ValueError("reference review targets a package reference")
        return self


class ContentReviewAssessment(_ReviewModel):
    """Closed supplied assessment; its claims still belong to its reviewer."""

    schema_version: Literal["content-review-assessment/v1"] = "content-review-assessment/v1"
    candidate: PackageCandidateIdentity
    reviewer: PackageSafetyReviewer
    evidence: tuple[PackageSafetyEvidenceReference, ...] = Field(min_length=1)
    items: tuple[ContentReviewItem, ...] = Field(min_length=2)

    @field_validator("evidence", mode="before")
    @classmethod
    def nested_evidence_is_revalidated(cls, value: object) -> object:
        if isinstance(value, (tuple, list)):
            try:
                return tuple(
                    item.model_dump(mode="python", warnings="error")
                    if isinstance(item, PackageSafetyEvidenceReference)
                    else item
                    for item in value
                )
            except PydanticSerializationError:
                raise ValueError("review evidence failed revalidation") from None
        return value

    @model_validator(mode="after")
    def review_has_closed_coverage(self) -> ContentReviewAssessment:
        ids = [item.evidence_id for item in self.evidence]
        keys = [(item.dimension, item.path) for item in self.items]
        if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
            raise ValueError("review evidence and dimension-path pairs must be unique")
        if not {("description", "SKILL.md"), ("progressive_disclosure", "SKILL.md")}.issubset(keys):
            raise ValueError("review must cover description and progressive disclosure")
        used = {evidence_id for item in self.items for evidence_id in item.evidence_ids}
        if used != set(ids):
            raise ValueError("every review evidence id must be declared and used")
        evidence_paths = {item.evidence_id: item.ref for item in self.evidence}
        if any(
            item.status != "gap" and item.path not in {evidence_paths[key] for key in item.evidence_ids}
            for item in self.items
        ):
            raise ValueError("completed dispositions require evidence for their own path")
        return self


class ContentReviewResult(_ReviewModel):
    """Result of binding supplied review evidence to the current package."""

    schema_version: Literal["content-review/v1"] = "content-review/v1"
    candidate: PackageCandidateIdentity | None
    status: Literal["pass", "blocked"]
    assessment: ContentReviewAssessment | None = None
    findings: tuple[SkillPackageFinding, ...] = ()
    semantic_review_executed: Literal[False] = False
    promotion_authorized: Literal[False] = False
    network_used: Literal[False] = False
    mutation_performed: Literal[False] = False

    @model_validator(mode="after")
    def result_matches_supplied_review(self) -> ContentReviewResult:
        if self.assessment is not None:
            ContentReviewAssessment.model_validate(self.assessment.model_dump(mode="json", warnings="error"))
        if self.status == "pass":
            if self.findings or self.assessment is None or self.candidate != self.assessment.candidate:
                raise ValueError("passing review requires matching assessment and no findings")
            if any(item.status != "clear" for item in self.assessment.items):
                raise ValueError("passing review cannot retain findings or gaps")
        elif not self.findings:
            raise ValueError("blocked review requires findings")
        return self


class ContentReviewExecutionResult(_ReviewModel):
    """Observed local callback invocation, separate from semantic truth."""

    schema_version: Literal["content-review-execution/v1"] = "content-review-execution/v1"
    candidate: PackageCandidateIdentity | None
    status: Literal["pass", "blocked"]
    adapter_invoked: bool = False
    reviewer: PackageSafetyReviewer | None = None
    review: ContentReviewResult | None = None
    assessment_sha256: Sha256 | None = None
    findings: tuple[SkillPackageFinding, ...] = ()
    promotion_authorized: Literal[False] = False

    @model_validator(mode="after")
    def execution_matches_observed_review(self) -> ContentReviewExecutionResult:
        if self.adapter_invoked and (self.candidate is None or self.reviewer is None):
            raise ValueError("adapter invocation requires candidate and reviewer binding")
        if self.review is not None:
            ContentReviewResult.model_validate(self.review.model_dump(mode="json", warnings="error"))
        assessment = self.review.assessment if self.review is not None else None
        expected = canonical_json_sha256(assessment.model_dump(mode="json")) if assessment is not None else None
        if self.assessment_sha256 != expected:
            raise ValueError("execution must bind the returned assessment digest")
        if self.status == "pass" and assessment is not None and self.reviewer != assessment.reviewer:
            raise ValueError("execution reviewer must match the returned assessment")
        if self.status == "pass":
            if not self.adapter_invoked or self.findings or self.review is None or self.review.status != "pass":
                raise ValueError("passing execution requires an invoked adapter and passing review")
            if self.candidate != self.review.candidate:
                raise ValueError("passing execution must bind the reviewed candidate")
        elif not self.findings:
            raise ValueError("blocked execution requires findings")
        return self


__all__ = ["ContentReviewAssessment", "ContentReviewExecutionResult", "ContentReviewItem", "ContentReviewResult"]
