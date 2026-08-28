"""Additive v2 evaluation contracts with provider-bound digest comparison."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.evaluation import ScorerProfile
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceiptBlocker, ReceiptId
from skills_sdk.models.provider import ProviderIdentityV2


class ScenarioCaseV2(_ContractModel):
    """One v2 scenario; exact match compares digests only."""

    case_id: NonEmptyText
    category: Literal["happy", "pressure", "boundary", "regression"]
    prompt: NonEmptyText
    expected_signals: tuple[NonEmptyText, ...] = Field(min_length=1)
    forbidden_commands: tuple[NonEmptyText, ...] = ()
    oracle: Literal["exact_match", "expected_signal", "structured"]
    expected_output_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def digest_belongs_only_to_exact_match(self) -> ScenarioCaseV2:
        if self.oracle != "exact_match" and self.expected_output_sha256 is not None:
            raise ValueError("expected_output_sha256 is valid only for exact_match scenarios")
        return self


class ScenarioSetV2(_ContractModel):
    schema_version: Literal["scenario-set/v2"] = "scenario-set/v2"
    candidate: PackageCandidateIdentity
    scenario_set_id: NonEmptyText
    release: bool
    cases: tuple[ScenarioCaseV2, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> ScenarioSetV2:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario case ids must be unique")
        if self.release and not any(case.category == "regression" for case in self.cases):
            raise ValueError("release scenario sets require a regression case")
        return self


class ScenarioObservationV2(_ContractModel):
    schema_version: Literal["scenario-observation/v2"] = "scenario-observation/v2"
    candidate: PackageCandidateIdentity
    scenario_set_id: NonEmptyText
    case_id: NonEmptyText
    provider: ProviderIdentityV2
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
    def status_matches_observation(self) -> ScenarioObservationV2:
        if self.status == "completed":
            if self.blocker is not None or self.output_sha256 is None:
                raise ValueError("completed scenario observation requires output and no blocker")
        elif self.blocker is None:
            raise ValueError("blocked scenario observation requires a blocker")
        elif self.output_sha256 is not None or self.observed_signals or self.observed_commands:
            raise ValueError("blocked scenario observation cannot claim completed output")
        return self


class ScenarioCaseResultV2(_ContractModel):
    schema_version: Literal["scenario-case-result/v2"] = "scenario-case-result/v2"
    candidate: PackageCandidateIdentity
    scenario_set_id: NonEmptyText
    case_id: NonEmptyText
    provider: ProviderIdentityV2
    status: Literal["pass", "fail", "blocked"]
    missing_signals: tuple[NonEmptyText, ...] = ()
    forbidden_commands_observed: tuple[NonEmptyText, ...] = ()
    evidence_refs: tuple[PortablePath, ...] = ()
    observation_sha256: Sha256 | None = None
    expected_output_sha256: Sha256 | None = None
    output_digest_mismatch: bool = False
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
    def status_matches_findings(self) -> ScenarioCaseResultV2:
        has_failure = bool(self.missing_signals or self.forbidden_commands_observed or self.output_digest_mismatch)
        if self.status == "pass" and (has_failure or self.blocker is not None):
            raise ValueError("passing scenario result cannot contain failures or a blocker")
        if self.status == "fail" and (not has_failure or self.blocker is not None):
            raise ValueError("failed scenario result requires deterministic failure evidence")
        if self.status == "blocked" and (self.blocker is None or has_failure or self.observation_sha256 is not None):
            raise ValueError("blocked scenario result requires only a blocker")
        if self.status != "blocked" and self.observation_sha256 is None:
            raise ValueError("completed scenario result requires observation_sha256")
        if self.output_digest_mismatch and self.expected_output_sha256 is None:
            raise ValueError("output digest mismatch requires the expected digest")
        if self.expected_output_sha256 is not None and self.observation_sha256 is not None:
            mismatch = self.expected_output_sha256 != self.observation_sha256
            if self.output_digest_mismatch != mismatch:
                raise ValueError("output digest mismatch must match the expected and observed digests")
        return self


class EvaluationReceiptV2(_ContractModel):
    schema_version: Literal["evaluation-receipt/v2"] = "evaluation-receipt/v2"
    receipt_id: ReceiptId
    candidate: PackageCandidateIdentity
    lane: Literal["evaluation"] = "evaluation"
    scenario_set_id: NonEmptyText
    provider: ProviderIdentityV2 | None = None
    scorer: ScorerProfile
    status: Literal["pass", "fail", "blocked"]
    score: float | None = Field(default=None, ge=0, le=1)
    case_results: tuple[ScenarioCaseResultV2, ...] = ()
    completed_calibration_probe_ids: tuple[NonEmptyText, ...] = ()
    blocker: PackageReceiptBlocker | None = None
    mutation_performed: Literal[False] = False

    @model_validator(mode="after")
    def receipt_is_bound(self) -> EvaluationReceiptV2:
        scorer_mismatch = (
            self.status == "blocked" and self.blocker is not None and self.blocker.code == "scorer_candidate_mismatch"
        )
        if self.scorer.candidate != self.candidate and not scorer_mismatch:
            raise ValueError("evaluation receipt scorer must bind the same candidate")
        ids = tuple(result.case_id for result in self.case_results)
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation receipt case ids must be unique")
        if any(
            result.candidate != self.candidate or result.scenario_set_id != self.scenario_set_id
            for result in self.case_results
        ):
            raise ValueError("evaluation receipt results must bind the same candidate and scenario set")
        if self.case_results and self.provider is None:
            raise ValueError("evaluation receipt with results must bind one provider")
        if self.provider is not None and any(result.provider != self.provider for result in self.case_results):
            raise ValueError("evaluation receipt results must bind the same provider")
        probes = tuple(self.completed_calibration_probe_ids)
        if len(probes) != len(set(probes)) or any(probe not in self.scorer.calibration_probe_ids for probe in probes):
            raise ValueError("completed calibration probes must be unique and declared")
        canonical = tuple(probe for probe in self.scorer.calibration_probe_ids if probe in set(probes))
        if probes != canonical:
            raise ValueError("completed calibration probes must follow scorer profile order")
        blocked_results = tuple(result for result in self.case_results if result.status == "blocked")
        if self.status == "blocked":
            if self.blocker is None and not blocked_results:
                raise ValueError("blocked evaluation receipt requires a blocker")
            if self.score is not None:
                raise ValueError("blocked evaluation receipt cannot claim a score")
        else:
            if self.provider is None or self.blocker is not None or blocked_results:
                raise ValueError("completed evaluation receipt requires one provider and no blockers")
            if self.score is None or not self.case_results or self.scorer.scorer_type != "deterministic":
                raise ValueError("completed evaluation receipt requires deterministic results and score")
            if self.scorer.calibration_required and set(probes) != set(self.scorer.calibration_probe_ids):
                raise ValueError("completed calibration probes must match the scorer profile")
            expected_score = sum(result.status == "pass" for result in self.case_results) / len(self.case_results)
            if self.score != expected_score:
                raise ValueError("evaluation receipt score must match the case-result pass ratio")
            expected_status = "pass" if self.score >= self.scorer.pass_threshold else "fail"
            if self.status != expected_status:
                raise ValueError("evaluation receipt status must match the scorer threshold")
        return self


__all__ = ["EvaluationReceiptV2", "ScenarioCaseResultV2", "ScenarioCaseV2", "ScenarioObservationV2", "ScenarioSetV2"]
