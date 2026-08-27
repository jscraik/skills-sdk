"""Portable scenario-set and scorer-profile contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceiptBlocker, ReceiptId


class ScenarioCase(_ContractModel):
    """One candidate-bound behavioral scenario."""

    case_id: NonEmptyText
    category: Literal["happy", "pressure", "boundary", "regression"]
    prompt: NonEmptyText
    expected_signals: tuple[NonEmptyText, ...] = Field(min_length=1)
    forbidden_commands: tuple[NonEmptyText, ...] = ()
    oracle: Literal["exact_match", "expected_signal", "structured"]


class ScenarioSet(_ContractModel):
    """Immutable scenario universe selected for one package candidate."""

    schema_version: Literal["scenario-set/v1"] = "scenario-set/v1"
    candidate: PackageCandidateIdentity
    scenario_set_id: NonEmptyText
    release: bool
    cases: tuple[ScenarioCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> ScenarioSet:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario case ids must be unique")
        if self.release and not any(case.category == "regression" for case in self.cases):
            raise ValueError("release scenario sets require a regression case")
        return self


class ScorerProfile(_ContractModel):
    """Versioned scorer identity and calibration requirements."""

    schema_version: Literal["scorer-profile/v1"] = "scorer-profile/v1"
    candidate: PackageCandidateIdentity
    scorer_id: NonEmptyText
    scorer_type: Literal["deterministic", "llm_judge", "hybrid", "external"]
    version_or_digest: NonEmptyText
    pass_threshold: float = Field(ge=0, le=1)
    deterministic_checks_first: bool
    calibration_required: bool
    calibration_probe_ids: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def calibration_matches_policy(self) -> ScorerProfile:
        if self.calibration_required and not self.calibration_probe_ids:
            raise ValueError("calibration_required scorers must declare calibration probes")
        if self.scorer_type in {"llm_judge", "external"} and not self.calibration_required:
            raise ValueError("judge and external scorers must require calibration")
        if self.scorer_type in {"llm_judge", "external"} and not self.deterministic_checks_first:
            raise ValueError("judge and external scorers must run deterministic checks first")
        if len(self.calibration_probe_ids) != len(set(self.calibration_probe_ids)):
            raise ValueError("calibration probe ids must be unique")
        return self


class ScenarioObservation(_ContractModel):
    """Redacted, candidate-bound output from an external scenario runner."""

    schema_version: Literal["scenario-observation/v1"] = "scenario-observation/v1"
    candidate: PackageCandidateIdentity
    scenario_set_id: NonEmptyText
    case_id: NonEmptyText
    status: Literal["completed", "blocked"]
    observed_signals: tuple[NonEmptyText, ...] = ()
    observed_commands: tuple[NonEmptyText, ...] = ()
    evidence_refs: tuple[PortablePath, ...] = ()
    output_sha256: Sha256 | None = None
    runner_id: NonEmptyText
    runner_version_or_digest: NonEmptyText
    blocker: PackageReceiptBlocker | None = None
    mutation_performed: Literal[False] = False

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("scenario observation evidence refs must be unique")
        for value in values:
            require_portable_relative_path(value)
        return values

    @model_validator(mode="after")
    def status_matches_observation(self) -> ScenarioObservation:
        if self.status == "completed":
            if self.blocker is not None:
                raise ValueError("completed scenario observation cannot contain a blocker")
            if self.output_sha256 is None:
                raise ValueError("completed scenario observation requires output_sha256")
        else:
            if self.blocker is None:
                raise ValueError("blocked scenario observation requires a blocker")
            if self.output_sha256 is not None or self.observed_signals or self.observed_commands:
                raise ValueError("blocked scenario observation cannot claim completed output")
        return self


class ScenarioCaseResult(_ContractModel):
    """One deterministic decision over a scenario observation."""

    schema_version: Literal["scenario-case-result/v1"] = "scenario-case-result/v1"
    candidate: PackageCandidateIdentity
    scenario_set_id: NonEmptyText
    case_id: NonEmptyText
    status: Literal["pass", "fail", "blocked"]
    missing_signals: tuple[NonEmptyText, ...] = ()
    forbidden_commands_observed: tuple[NonEmptyText, ...] = ()
    evidence_refs: tuple[PortablePath, ...] = ()
    observation_sha256: Sha256 | None = None
    runner_id: NonEmptyText
    runner_version_or_digest: NonEmptyText
    blocker: PackageReceiptBlocker | None = None
    mutation_performed: Literal[False] = False

    @field_validator("evidence_refs")
    @classmethod
    def result_refs_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("scenario result evidence refs must be unique")
        for value in values:
            require_portable_relative_path(value)
        return values

    @model_validator(mode="after")
    def status_matches_findings(self) -> ScenarioCaseResult:
        has_failure = bool(self.missing_signals or self.forbidden_commands_observed)
        if self.status == "pass" and (has_failure or self.blocker is not None):
            raise ValueError("passing scenario result cannot contain failures or a blocker")
        if self.status == "fail" and (not has_failure or self.blocker is not None):
            raise ValueError("failed scenario result requires deterministic failure evidence")
        if self.status == "blocked" and self.blocker is None:
            raise ValueError("blocked scenario result requires a blocker")
        if self.status != "blocked" and self.observation_sha256 is None:
            raise ValueError("completed scenario result requires observation_sha256")
        if self.status == "blocked" and self.observation_sha256 is not None:
            raise ValueError("blocked scenario result cannot claim an observation digest")
        return self


class EvaluationReceipt(_ContractModel):
    """Deterministic, candidate-bound local evaluation result."""

    schema_version: Literal["evaluation-receipt/v1"] = "evaluation-receipt/v1"
    receipt_id: ReceiptId
    candidate: PackageCandidateIdentity
    lane: Literal["evaluation"] = "evaluation"
    scenario_set_id: NonEmptyText
    scorer: ScorerProfile
    status: Literal["pass", "fail", "blocked"]
    score: float | None = Field(default=None, ge=0, le=1)
    case_results: tuple[ScenarioCaseResult, ...] = ()
    completed_calibration_probe_ids: tuple[NonEmptyText, ...] = ()
    blocker: PackageReceiptBlocker | None = None
    mutation_performed: Literal[False] = False

    @model_validator(mode="after")
    def receipt_is_candidate_bound(self) -> EvaluationReceipt:
        scorer_mismatch_blocked = (
            self.status == "blocked"
            and self.blocker is not None
            and self.blocker.code == "scorer_candidate_mismatch"
        )
        if self.scorer.candidate != self.candidate and not scorer_mismatch_blocked:
            raise ValueError("evaluation receipt scorer must bind the same candidate")
        case_ids = tuple(result.case_id for result in self.case_results)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation receipt case ids must be unique")
        if any(
            result.candidate != self.candidate or result.scenario_set_id != self.scenario_set_id
            for result in self.case_results
        ):
            raise ValueError("evaluation receipt results must bind the same candidate and scenario set")
        if len(self.completed_calibration_probe_ids) != len(set(self.completed_calibration_probe_ids)):
            raise ValueError("completed calibration probe ids must be unique")
        completed_probe_set = set(self.completed_calibration_probe_ids)
        declared_probe_set = set(self.scorer.calibration_probe_ids)
        if completed_probe_set - declared_probe_set:
            raise ValueError("completed calibration probes must be declared by the scorer profile")
        canonical_completed_probes = tuple(
            probe for probe in self.scorer.calibration_probe_ids if probe in completed_probe_set
        )
        if self.completed_calibration_probe_ids != canonical_completed_probes:
            raise ValueError("completed calibration probes must follow scorer profile order")
        if (
            self.status != "blocked"
            and self.scorer.calibration_required
            and completed_probe_set != declared_probe_set
        ):
            raise ValueError("completed calibration probes must match the scorer profile")
        blocked_results = tuple(result for result in self.case_results if result.status == "blocked")
        if self.status == "blocked":
            if self.blocker is None and not blocked_results:
                raise ValueError("blocked evaluation receipt requires a blocker")
            if self.score is not None:
                raise ValueError("blocked evaluation receipt cannot claim a score")
        else:
            if self.blocker is not None or blocked_results:
                raise ValueError("completed evaluation receipt cannot contain blockers")
            if self.score is None or not self.case_results:
                raise ValueError("completed evaluation receipt requires score and case results")
            expected_status = "pass" if self.score >= self.scorer.pass_threshold else "fail"
            if self.status != expected_status:
                raise ValueError("evaluation receipt status must match the scorer threshold")
        return self


__all__ = [
    "EvaluationReceipt",
    "ScenarioCase",
    "ScenarioCaseResult",
    "ScenarioObservation",
    "ScenarioSet",
    "ScorerProfile",
]
