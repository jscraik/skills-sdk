"""Executed calibration contracts; supplied assessment v1 remains read-only."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from skills_sdk.models.evaluation import ScorerProfile
from skills_sdk.models.inventory import NonEmptyText, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_execution import _identity_is_public
from skills_sdk.models.safety import PackageSafetyBlocker
from skills_sdk.models.scorer_quality import ScorerCalibrationAppliedPolicy, ScorerJudgeParameters
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence


def _audit_copied_members(value: object) -> None:
    """Reject hidden copied members before a serializer can omit or coerce them."""
    stack = [(value, 0, False)]
    active: set[int] = set()
    completed: set[int] = set()
    remaining = 4096
    while stack:
        item, depth, leaving = stack.pop()
        identity = id(item)
        if leaving:
            active.remove(identity)
            completed.add(identity)
            continue
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise ValueError("calibration input exceeds its nesting or work boundary")
        if not isinstance(item, (BaseModel, dict, tuple, list)):
            continue
        if identity in active:
            raise ValueError("calibration input contains a cycle")
        if identity in completed:
            continue
        if isinstance(item, BaseModel):
            if set(item.__dict__) - set(type(item).model_fields) or item.__pydantic_extra__:
                raise ValueError("copied calibration models contain unknown fields")
            members = tuple(item.__dict__.values())
        elif isinstance(item, dict):
            members = tuple(item.values())
        else:
            members = item
        if len(members) > remaining:
            raise ValueError("calibration input exceeds its work boundary")
        active.add(identity)
        stack.append((item, depth, True))
        stack.extend((member, depth + 1, False) for member in members)


class _ObservedContractModel(_ContractModel):
    """Revalidate copied instances without changing frozen contract families."""

    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def copied_members_are_explicit(cls, value: object) -> object:
        """Preserve unknown-field rejection for typed and mixed nested inputs."""
        _audit_copied_members(value)
        return value


class HeldOutCalibrationProbe(_ObservedContractModel):
    """A host-retained label bound to the exact held-out provider output."""

    probe_id: NonEmptyText
    output_sha256: Sha256
    expected_label: Literal["pass", "fail"]


class ObservedCalibrationPlan(_ObservedContractModel):
    """Freeze candidate, judge, parameters, scorer, held-out outputs and policy."""

    schema_version: Literal["observed-calibration-plan/v1"] = "observed-calibration-plan/v1"
    candidate: PackageCandidateIdentity
    scorer: ScorerProfile
    judge: ProviderIdentityV2
    parameters: ScorerJudgeParameters
    policy: ScorerCalibrationAppliedPolicy
    assertion_contract_sha256: Sha256
    probes: tuple[HeldOutCalibrationProbe, ...] = Field(min_length=2, max_length=64)

    @field_validator("candidate", "scorer", "judge", "parameters", "policy", "probes", mode="before")
    @classmethod
    def normalize_nested_models(cls, value: object) -> object:
        """Revalidate copied members without laundering bools into numeric fields."""
        _audit_copied_members(value)
        if isinstance(value, BaseModel):
            return value.model_dump(mode="python")
        if isinstance(value, (tuple, list)):
            return [item.model_dump(mode="python") if isinstance(item, BaseModel) else item for item in value]
        return value

    @model_validator(mode="after")
    def bindings_and_coverage(self) -> ObservedCalibrationPlan:
        """Reject contradictory coverage rather than accepting caller completion IDs."""
        public_values = [
            *self.candidate.model_dump(mode="json").values(),
            self.scorer.scorer_id,
            self.scorer.version_or_digest,
            self.parameters.model,
            *self.scorer.calibration_probe_ids,
            *self.judge.model_dump(mode="json").values(),
        ]
        if any(not isinstance(value, str) or not _identity_is_public(value) for value in public_values):
            raise ValueError("calibration identities must be portable and public")
        if self.scorer.candidate != self.candidate or not self.scorer.calibration_required:
            raise ValueError("observed calibration requires the candidate's calibration-required scorer")
        if tuple(probe.probe_id for probe in self.probes) != self.scorer.calibration_probe_ids:
            raise ValueError("held-out probes must exactly match declared scorer order")
        if len({probe.output_sha256 for probe in self.probes}) != len(self.probes):
            raise ValueError("held-out outputs must be distinct")
        if {probe.expected_label for probe in self.probes} != {"pass", "fail"}:
            raise ValueError("calibration needs positive and negative held-out labels")
        if self.parameters.model != self.judge.model_id:
            raise ValueError("calibration parameters must bind the judge model")
        if self.policy.threshold != self.scorer.pass_threshold:
            raise ValueError("calibration threshold must bind the scorer")
        if len(self.probes) < self.policy.minimum_examples:
            raise ValueError("calibration coverage is below policy")
        if len(self.probes) * self.parameters.trial_count > 128:
            raise ValueError("observed calibration is bounded to 128 executions")
        return self


class CalibrationJudgeVerdict(_ObservedContractModel):
    """Numeric judgment from an invoked adapter, bound to its actual output."""

    evidence: SelectedCaseJudgeEvidence
    score: float = Field(ge=0, le=1, strict=True, allow_inf_nan=False)

    @field_validator("evidence", mode="before")
    @classmethod
    def revalidate_evidence(cls, value: object) -> object:
        """Do not trust copied nested judge evidence models."""
        return ObservedCalibrationPlan.normalize_nested_models(value)


class ObservedCalibrationProbeResult(_ObservedContractModel):
    """Redacted per-output execution result; raw outputs never enter the receipt."""

    probe_id: NonEmptyText
    trial_index: int = Field(ge=0, strict=True)
    output_sha256: Sha256
    expected_label: Literal["pass", "fail"]
    predicted_label: Literal["pass", "fail"]
    score: float = Field(ge=0, le=1, strict=True, allow_inf_nan=False)
    judge_result_sha256: Sha256


class ObservedCalibrationReceipt(_ObservedContractModel):
    """Observed callback proof, not authenticated external judge or promotion proof."""

    schema_version: Literal["observed-calibration/v1"] = "observed-calibration/v1"
    plan: ObservedCalibrationPlan | None = None
    status: Literal["pass", "blocked"]
    results: tuple[ObservedCalibrationProbeResult, ...] = ()
    blocker: PackageSafetyBlocker | None = None
    judge_invocation_count: int = Field(ge=0, le=128, strict=True)
    judge_execution_performed: bool = Field(strict=True)
    evidence_scope: Literal["observed_adapter_callbacks"] = "observed_adapter_callbacks"
    external_authenticity_verified: Literal[False] = False
    mutation_performed: Literal[False] = False
    promotion_authorized: Literal[False] = False

    @field_validator("mutation_performed", "promotion_authorized", "external_authenticity_verified", mode="before")
    @classmethod
    def false_only(cls, value: object) -> object:
        """Keep model and JSON schema false-only boundaries identical."""
        if value is not False:
            raise ValueError("observed calibration cannot authorise mutation or promotion")
        return value

    @field_validator("plan", "results", "blocker", mode="before")
    @classmethod
    def normalize_nested_models(cls, value: object) -> object:
        """Revalidate nested copied models, including blocked partial results."""
        return ObservedCalibrationPlan.normalize_nested_models(value)

    @model_validator(mode="after")
    def completed_results_bind_plan(self) -> ObservedCalibrationReceipt:
        """Require full ordered execution coverage and confusion-matrix policy."""
        if (
            self.judge_execution_performed != (self.judge_invocation_count > 0)
            or len(self.results) > self.judge_invocation_count
        ):
            raise ValueError("executed calibration results must match execution flag")
        if self.plan is None:
            if self.results or self.status != "blocked" or self.blocker is None or self.judge_invocation_count:
                raise ValueError("calibration without a plan requires a pre-execution blocker")
            if self.blocker.code != "invalid_calibration_input":
                raise ValueError("calibration without a plan requires an input blocker")
            return self
        expected = [(probe, trial) for probe in self.plan.probes for trial in range(self.plan.parameters.trial_count)]
        if self.judge_invocation_count > len(expected):
            raise ValueError("calibration invocations cannot exceed the declared batch")
        counts = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
        for result, (probe, trial) in zip(self.results, expected[: len(self.results)], strict=True):
            if result.trial_index != trial or (result.probe_id, result.output_sha256, result.expected_label) != (
                probe.probe_id,
                probe.output_sha256,
                probe.expected_label,
            ):
                raise ValueError("executed calibration must bind ordered held-out outputs")
            predicted = "pass" if result.score >= self.plan.policy.threshold else "fail"
            if result.predicted_label != predicted:
                raise ValueError("calibration verdict must use the frozen threshold")
            key = {("pass", "pass"): "tp", ("fail", "fail"): "tn", ("fail", "pass"): "fp", ("pass", "fail"): "fn"}
            counts[key[(result.expected_label, result.predicted_label)]] += 1
        if self.status == "blocked":
            if self.blocker is None:
                raise ValueError("blocked calibration requires a typed blocker")
            if self.judge_invocation_count > len(self.results) + 1:
                raise ValueError("first-stop calibration cannot retain multiple unrecorded invocations")
            self._blocked_evidence_matches_code(counts, len(expected))
            return self
        if self.blocker is not None or not self.judge_execution_performed:
            raise ValueError("passing calibration requires a complete executed plan")
        if len(self.results) != len(expected) or self.judge_invocation_count != len(expected):
            raise ValueError("partial calibration cannot pass")
        policy = self.plan.policy
        if (
            counts["tp"] < policy.minimum_true_positives
            or counts["tn"] < policy.minimum_true_negatives
            or counts["fp"] > policy.max_false_positives
            or counts["fn"] > policy.max_false_negatives
        ):
            raise ValueError("executed calibration does not satisfy its confusion-matrix policy")
        return self

    def _blocked_evidence_matches_code(self, counts: dict[str, int], expected_count: int) -> None:
        """Recovery codes must describe the evidence the sequential service retained."""
        assert self.blocker is not None and self.plan is not None
        if self.blocker.code == "calibration_policy_failed":
            policy = self.plan.policy
            failed = (
                counts["tp"] < policy.minimum_true_positives
                or counts["tn"] < policy.minimum_true_negatives
                or counts["fp"] > policy.max_false_positives
                or counts["fn"] > policy.max_false_negatives
            )
            if len(self.results) != expected_count or self.judge_invocation_count != expected_count or not failed:
                raise ValueError("policy failure requires complete observed results failing the frozen policy")
        elif self.blocker.code in {"calibration_execution_failed", "calibration_execution_incomplete"}:
            if len(self.results) >= expected_count:
                raise ValueError("execution failure requires an unfinished result prefix")
        elif self.results or self.judge_invocation_count:
            raise ValueError("pre-execution blockers cannot retain judge invocations")
