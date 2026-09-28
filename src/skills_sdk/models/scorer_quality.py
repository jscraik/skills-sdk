"""Candidate-bound, read-only scorer assessment receipts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from skills_sdk.models.inventory import NonEmptyText, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.scenario_quality import ScenarioQualityFinding


class ScorerQualityReceipt(_ContractModel):
    schema_version: Literal["scorer-quality/v1"] = "scorer-quality/v1"
    candidate: PackageCandidateIdentity | None = None
    status: Literal["pass", "blocked"]
    scorer_id: str = ""
    scorer_version_or_digest: str = ""
    pass_threshold: float | None = Field(default=None, gt=0, le=1, strict=True)
    calibration_probe_count: int = Field(default=0, ge=0, strict=True)
    findings: tuple[ScenarioQualityFinding, ...] = ()
    mutation_performed: Literal[False] = False
    network_used: Literal[False] = False
    execution_performed: Literal[False] = False

    @model_validator(mode="after")
    def status_matches_findings(self) -> ScorerQualityReceipt:
        if self.status == "pass" and (
            self.candidate is None
            or self.findings
            or self.calibration_probe_count < 6
            or not self.scorer_id.strip()
            or not self.scorer_version_or_digest.strip()
            or self.pass_threshold is None
        ):
            raise ValueError("passing scorer quality requires a candidate, probes, and no findings")
        if self.status == "blocked" and not self.findings:
            raise ValueError("blocked scorer quality requires findings")
        return self


class ScorerCalibrationMetrics(_ContractModel):
    tp: int = Field(ge=0, strict=True)
    tn: int = Field(ge=0, strict=True)
    fp: int = Field(ge=0, strict=True)
    fn: int = Field(ge=0, strict=True)


class ScorerCalibrationAppliedPolicy(_ContractModel):
    threshold: float = Field(gt=0, le=1, strict=True)
    minimum_examples: int = Field(ge=1, strict=True)
    minimum_true_positives: int = Field(ge=1, strict=True)
    minimum_true_negatives: int = Field(ge=1, strict=True)
    max_false_positives: int = Field(ge=0, strict=True)
    max_false_negatives: int = Field(ge=0, strict=True)


class ScorerJudgeParameters(_ContractModel):
    model: NonEmptyText
    temperature: float = Field(allow_inf_nan=False, strict=True)
    trial_count: int = Field(ge=1, strict=True)


class ScorerCalibrationRates(_ContractModel):
    tpr: float | None = Field(default=None, ge=0, le=1, strict=True)
    tnr: float | None = Field(default=None, ge=0, le=1, strict=True)
    precision: float | None = Field(default=None, ge=0, le=1, strict=True)
    accuracy: float | None = Field(default=None, ge=0, le=1, strict=True)


class ScorerCalibrationReceipt(_ContractModel):
    schema_version: Literal["scorer-calibration/v1"] = "scorer-calibration/v1"
    candidate: PackageCandidateIdentity | None = None
    status: Literal["pass", "blocked"]
    scorer_id: str = ""
    scorer_version_or_digest: str = ""
    prompt_version: str = ""
    parameters: ScorerJudgeParameters | None = None
    example_count: int = Field(default=0, ge=0, strict=True)
    effective_policy: ScorerCalibrationAppliedPolicy | None = None
    confusion_matrix: ScorerCalibrationMetrics = Field(
        default_factory=lambda: ScorerCalibrationMetrics(tp=0, tn=0, fp=0, fn=0)
    )
    metrics: ScorerCalibrationRates = Field(default_factory=ScorerCalibrationRates)
    findings: tuple[ScenarioQualityFinding, ...] = ()
    mutation_performed: Literal[False] = False
    network_used: Literal[False] = False
    execution_performed: Literal[False] = False

    @model_validator(mode="after")
    def status_matches_findings(self) -> ScorerCalibrationReceipt:
        if self.status == "pass" and (
            self.candidate is None
            or self.findings
            or self.example_count == 0
            or self.effective_policy is None
            or self.parameters is None
            or not self.scorer_id.strip()
            or not self.scorer_version_or_digest.strip()
            or not self.prompt_version.strip()
        ):
            raise ValueError("passing calibration requires a candidate, examples, and no findings")
        if self.status == "pass" and self.effective_policy is not None:
            policy = self.effective_policy
            matrix = self.confusion_matrix
            if (
                self.example_count != matrix.tp + matrix.tn + matrix.fp + matrix.fn
                or self.example_count < policy.minimum_examples
                or matrix.tp < policy.minimum_true_positives
                or matrix.tn < policy.minimum_true_negatives
                or matrix.fp > policy.max_false_positives
                or matrix.fn > policy.max_false_negatives
            ):
                raise ValueError("passing calibration must satisfy its effective policy")
            expected_rates = (
                round(matrix.tp / (matrix.tp + matrix.fn), 6),
                round(matrix.tn / (matrix.tn + matrix.fp), 6),
                round(matrix.tp / (matrix.tp + matrix.fp), 6),
                round((matrix.tp + matrix.tn) / self.example_count, 6),
            )
            if (
                self.metrics.tpr,
                self.metrics.tnr,
                self.metrics.precision,
                self.metrics.accuracy,
            ) != expected_rates:
                raise ValueError("passing calibration metrics must match the confusion matrix")
        if self.status == "blocked" and not self.findings:
            raise ValueError("blocked calibration requires findings")
        return self


__all__ = [
    "ScorerCalibrationAppliedPolicy",
    "ScorerCalibrationMetrics",
    "ScorerCalibrationRates",
    "ScorerCalibrationReceipt",
    "ScorerJudgeParameters",
    "ScorerQualityReceipt",
]
