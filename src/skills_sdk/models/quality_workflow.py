"""Explicit intent and applicable policy for the additive local quality workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from skills_sdk.core.digests import candidate_content_sha256
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.content_review import (
    ContentReviewAssessment,
    ContentReviewExecutionResult,
    ContentReviewItem,
    ContentReviewResult,
)
from skills_sdk.models.coverage import ScenarioCoveragePlan, ScenarioCoverageResult
from skills_sdk.models.intake import SkillPackageIntakeContext, SkillPackageIntakeReceipt, _intake_evidence_data
from skills_sdk.models.inventory import PortablePath, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.safety import PackageSafetyEvidenceReference, PackageSafetyReviewer
from skills_sdk.models.scorer_quality import ScorerCalibrationReceipt, ScorerQualityReceipt
from skills_sdk.models.validation import SkillPackageFinding, SkillPackageValidation


def _review_types_are_canonical(value: object) -> None:
    """Preserve review canonical-only rules before typed evidence loses its class."""
    canonical = (
        ContentReviewAssessment,
        ContentReviewExecutionResult,
        ContentReviewItem,
        ContentReviewResult,
        PackageCandidateIdentity,
        PackageSafetyEvidenceReference,
        PackageSafetyReviewer,
        SkillPackageFinding,
    )
    pending, visited = [value], set()
    while pending:
        item = pending.pop()
        if id(item) in visited:
            continue
        visited.add(id(item))
        if isinstance(item, canonical) and type(item) not in canonical:
            raise ValueError("quality evidence requires canonical review contract models")
        if isinstance(item, _ContractModel):
            pending.extend(dict(item).values())
        elif isinstance(item, Mapping):
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)


def _validation_manifest_matches(validation: SkillPackageValidation) -> None:
    """Check internal manifest consistency, without authenticating source execution."""
    if (
        validation.candidate is not None
        and candidate_content_sha256(validation.files) != validation.candidate.content_sha256
    ):
        raise ValueError("quality capture digest must match its manifest files")


def _calibration_matches_declaration(calibration: ScorerCalibrationReceipt, declaration: QualityStageReceipt) -> None:
    """Join passing calibration to its scorer, retaining failed evidence as failure."""
    if calibration.status != "pass":
        return
    if not isinstance(declaration, ScorerQualityReceipt) or (
        calibration.scorer_id != declaration.scorer_id
        or calibration.scorer_version_or_digest != declaration.scorer_version_or_digest
        or calibration.effective_policy is None
        or calibration.effective_policy.threshold != declaration.pass_threshold
        or (declaration.parameters is not None and calibration.parameters != declaration.parameters)
    ):
        raise ValueError("passing calibration must match the declared scorer")


def _review_matches_capture(
    receipt: ContentReviewResult | ContentReviewExecutionResult, capture: QualityStageReceipt
) -> None:
    """Bind passing review digests and actual reference coverage to captured files."""
    if receipt.status != "pass":
        return
    review = receipt.review if isinstance(receipt, ContentReviewExecutionResult) else receipt
    if review is None or review.assessment is None or not isinstance(capture, SkillPackageValidation):
        raise ValueError("passing review requires a captured manifest")
    assessment = review.assessment
    files = {item.path: item.sha256 for item in capture.files}
    expected = {path for path in files if path.startswith("references/")}
    reviewed = {item.path for item in assessment.items if item.dimension == "reference"}
    if reviewed != expected or any(files.get(item.ref) != item.sha256 for item in assessment.evidence):
        raise ValueError("passing review evidence and coverage must match the captured manifest")


class LocalQualityPolicy(_ContractModel):
    """Persist selected deterministic checks without asserting that they ran."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    max_entrypoint_lines: StrictInt | None = Field(default=None, ge=0)
    max_reference_depth: StrictInt | None = Field(default=None, ge=0)
    required_files: tuple[PortablePath, ...] = Field(default=(), json_schema_extra={"uniqueItems": True})
    check_reference_content: StrictBool = False

    @field_validator("required_files", mode="before")
    @classmethod
    def required_files_are_materialized(cls, value: object) -> object:
        """Reject streaming selectors instead of silently consuming caller state."""
        if not isinstance(value, (list, tuple)):
            raise ValueError("required files must be a list or tuple")
        return value

    @field_validator("required_files")
    @classmethod
    def required_files_are_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require distinct package-relative file selectors."""
        for value in values:
            require_portable_relative_path(value)
        if len(values) != len(set(values)):
            raise ValueError("required files must be unique")
        return values


class LocalCheckRequestV2(_ContractModel):
    """Bind supplied workflow inputs; baseline and source still need observation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"intent": {"const": "update"}}, "required": ["intent"]},
                    "then": {"required": ["update_baseline"], "properties": {"update_baseline": {"type": "object"}}},
                    "else": {"properties": {"update_baseline": {"type": "null"}}},
                }
            ],
            "$comment": "Candidate equality and update lineage require the model or SchemaRegistry semantic validator.",
        },
    )

    schema_version: Literal["local-check-request/v2"] = "local-check-request/v2"
    intent: Literal["create", "update", "external-check"]
    candidate: PackageCandidateIdentity
    intake: SkillPackageIntakeContext
    policy: LocalQualityPolicy
    coverage_plan: ScenarioCoveragePlan
    content_review_mode: Literal["supplied", "observed"]
    update_baseline: PackageCandidateIdentity | None = None

    @model_validator(mode="before")
    @classmethod
    def inputs_are_revalidated(cls, value: object) -> object:
        """Reuse bounded contract traversal so forged nested instances are checked."""
        _review_types_are_canonical(value)
        normalized = _intake_evidence_data(value)
        pending = [normalized]
        while pending:
            item = pending.pop()
            if isinstance(item, (bytes, bytearray, memoryview)):
                raise ValueError("quality workflow inputs require JSON text")
            if isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, (list, tuple)):
                pending.extend(item)
        return normalized

    @model_validator(mode="after")
    def inputs_bind_candidate_and_intent(self) -> LocalCheckRequestV2:
        """Reject contradictory bindings without treating declarations as proof."""
        if self.intake.source_revision != self.candidate.source_revision:
            raise ValueError("intake revision must match the selected candidate")
        if self.coverage_plan.candidate != self.candidate:
            raise ValueError("coverage plan must match the selected candidate")
        if self.intent == "update":
            if self.update_baseline is None:
                raise ValueError("update baseline is required for update intent")
            if self.update_baseline.package_id != self.candidate.package_id:
                raise ValueError("update baseline must identify the same package")
        elif self.update_baseline is not None:
            raise ValueError("only update intent accepts an update baseline")
        return self


QualityStageName = Literal[
    "baseline", "intake", "validate", "scenario-coverage", "scorer-quality", "scorer-calibration", "content-review"
]
QualityStageReceipt = (
    SkillPackageValidation
    | SkillPackageIntakeReceipt
    | ScenarioCoverageResult
    | ScorerQualityReceipt
    | ScorerCalibrationReceipt
    | ContentReviewResult
    | ContentReviewExecutionResult
)
_QUALITY_TYPES = {
    "baseline": (SkillPackageValidation,),
    "intake": (SkillPackageIntakeReceipt,),
    "validate": (SkillPackageValidation,),
    "scenario-coverage": (ScenarioCoverageResult,),
    "scorer-quality": (ScorerQualityReceipt,),
    "scorer-calibration": (ScorerCalibrationReceipt,),
    "content-review": (ContentReviewResult, ContentReviewExecutionResult),
}


class LocalQualityStage(_ContractModel):
    """Retain each actual upstream service receipt without altering its meaning."""

    model_config = ConfigDict(revalidate_instances="always")
    name: QualityStageName
    receipt: QualityStageReceipt

    @model_validator(mode="before")
    @classmethod
    def stage_evidence_is_revalidated(cls, value: object) -> object:
        """Inspect typed nested evidence at the standalone stage boundary too."""
        return LocalCheckRequestV2.inputs_are_revalidated(value)

    @model_validator(mode="after")
    def receipt_matches_name(self) -> LocalQualityStage:
        """Require the stage's canonical receipt type and consistent validation manifests."""
        if type(self.receipt) not in _QUALITY_TYPES[self.name]:
            raise ValueError("quality stage must use its canonical receipt type")
        if isinstance(self.receipt, SkillPackageValidation):
            _validation_manifest_matches(self.receipt)
        elif isinstance(self.receipt, SkillPackageIntakeReceipt):
            _validation_manifest_matches(self.receipt.validation)
        return self

    def passed(self) -> bool:
        """Distinguish admission and complete coverage from a passing audit."""
        if isinstance(self.receipt, SkillPackageIntakeReceipt):
            return (
                self.receipt.status == "normalized"
                and self.receipt.decision is not None
                and self.receipt.decision.decision.value == "admit"
            )
        if isinstance(self.receipt, ScenarioCoverageResult):
            return self.receipt.status == "pass" and self.receipt.coverage_complete
        return self.receipt.status == "pass"


class LocalCheckResultV2(_ContractModel):
    """Ordered local quality evidence; never admission or promotion permission."""

    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["local-check/v2"] = "local-check/v2"
    status: Literal["local_checks_passed", "blocked"]
    request: LocalCheckRequestV2 | None
    stages: tuple[LocalQualityStage, ...] = ()
    final_capture: SkillPackageValidation | None = None
    baseline_final_capture: SkillPackageValidation | None = None
    blocked_stage: QualityStageName | Literal["request", "candidate_changed", "final-capture"] | None = None
    blocker: PackageReceiptBlocker | None = None
    promotion_authorized: Literal[False] = False
    evaluation_executed: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def evidence_is_revalidated(cls, value: object) -> object:
        """Revalidate nested evidence and require literal false values for proof flags."""
        normalized = LocalCheckRequestV2.inputs_are_revalidated(value)
        if isinstance(normalized, dict):
            for name in ("promotion_authorized", "evaluation_executed"):
                if name in normalized and normalized[name] is not False:
                    raise ValueError("quality proof flags require literal false")
        return normalized

    @model_validator(mode="after")
    def result_matches_ordered_evidence(self) -> LocalCheckResultV2:
        """Require ordered, candidate-bound receipts and captures that justify the result."""
        if self.request is None:
            if (
                self.status != "blocked"
                or self.stages
                or self.blocked_stage != "request"
                or self.blocker is None
                or self.final_capture is not None
                or self.baseline_final_capture is not None
            ):
                raise ValueError("invalid request requires an empty blocked result")
            return self
        expected = tuple(_QUALITY_TYPES)
        if self.request.intent != "update":
            expected = expected[1:]
        if tuple(stage.name for stage in self.stages) != expected[: len(self.stages)]:
            raise ValueError("quality stages must be an ordered prefix")
        mismatches = []
        receipts = {stage.name: stage.receipt for stage in self.stages}
        for index, stage in enumerate(self.stages):
            candidate = self.request.update_baseline if stage.name == "baseline" else self.request.candidate
            if stage.receipt.candidate != candidate:
                mismatches.append(index)
                if self.blocked_stage != "candidate_changed" or index != len(self.stages) - 1:
                    raise ValueError("quality stage must bind the selected candidate")
            if index < len(self.stages) - 1 and not stage.passed():
                raise ValueError("quality workflow must stop at the first incomplete stage")
            if isinstance(stage.receipt, SkillPackageIntakeReceipt) and stage.receipt.context != self.request.intake:
                raise ValueError("intake receipt must retain the selected request context")
            if isinstance(stage.receipt, ScenarioCoverageResult) and stage.receipt.plan != self.request.coverage_plan:
                raise ValueError("coverage receipt must retain the selected request plan")
            if isinstance(stage.receipt, ScorerCalibrationReceipt) and stage.receipt.candidate == candidate:
                _calibration_matches_declaration(stage.receipt, receipts["scorer-quality"])
            if stage.name == "content-review":
                observed = isinstance(stage.receipt, ContentReviewExecutionResult)
                if observed != (self.request.content_review_mode == "observed"):
                    raise ValueError("content evidence must match the selected review lane")
                if (
                    isinstance(stage.receipt, (ContentReviewResult, ContentReviewExecutionResult))
                    and stage.receipt.candidate == candidate
                ):
                    _review_matches_capture(stage.receipt, receipts["validate"])
        if (self.final_capture is not None or self.baseline_final_capture is not None) and (
            len(self.stages) != len(expected) or not all(stage.passed() for stage in self.stages)
        ):
            raise ValueError("final captures require every quality stage to pass")
        if self.request.intent != "update" and self.baseline_final_capture is not None:
            raise ValueError("only update intent permits a final baseline capture")
        for capture in (self.final_capture, self.baseline_final_capture):
            if capture is not None:
                _validation_manifest_matches(capture)
        if self.status == "local_checks_passed":
            if self.blocker is not None or self.blocked_stage is not None or len(self.stages) != len(expected):
                raise ValueError("passing quality workflow requires every stage")
            if not all(stage.passed() for stage in self.stages):
                raise ValueError("passing quality workflow requires complete passing evidence")
            if not self._captures_passed():
                raise ValueError("passing quality workflow requires unchanged final captures")
        elif self.blocker is None or self.blocked_stage is None:
            raise ValueError("blocked quality workflow requires a typed blocker and stage")
        elif self.blocked_stage == "candidate_changed":
            if mismatches != [len(self.stages) - 1]:
                raise ValueError("candidate change requires an actual last-stage mismatch")
        elif self.blocked_stage == "final-capture":
            if self.final_capture is None or self._captures_passed():
                raise ValueError("final capture blocker requires failed or changed capture evidence")
        elif self.blocker.code == "quality_input_missing":
            if len(self.stages) >= len(expected) or self.blocked_stage != expected[len(self.stages)]:
                raise ValueError("missing stage input must stop before the next stage")
            if not all(stage.passed() for stage in self.stages):
                raise ValueError("missing stage input requires passing upstream evidence")
        elif not self.stages or self.blocked_stage != self.stages[-1].name or self.stages[-1].passed():
            raise ValueError("blocked workflow must identify the first incomplete stage")
        return self

    def _captures_passed(self) -> bool:
        """Check the observed final identities, including update baseline freshness."""
        if self.request is None or self.final_capture is None:
            return False
        if self.final_capture.status != "pass" or self.final_capture.candidate != self.request.candidate:
            return False
        if self.request.intent == "update":
            return (
                self.baseline_final_capture is not None
                and self.baseline_final_capture.status == "pass"
                and self.baseline_final_capture.candidate == self.request.update_baseline
            )
        return True


__all__ = ["LocalCheckRequestV2", "LocalCheckResultV2", "LocalQualityPolicy", "LocalQualityStage"]
