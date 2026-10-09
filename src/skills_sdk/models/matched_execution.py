"""Observed matched-lane execution and ordered comparison evidence."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.models.evaluation_v2 import EvaluationReceiptV2
from skills_sdk.models.matched_calibration import (
    _dimension_digest,
    _dimension_score,
)
from skills_sdk.models.matched_comparison import (
    MatchedComparisonPlan,
    MatchedLaneSpec,
    MatchedPairAssessment,
    MatchedVariantJudgment,
    _matched_pair_values,
    _matched_weighted_score,
)
from skills_sdk.models.matched_ingress import _MatchedContractModel
from skills_sdk.models.matched_plugin_calibration import MatchedVariantCalibrationBundle, _require_variant_calibration
from skills_sdk.models.matched_policy import MatchedLaneSummary, build_matched_lane_summary
from skills_sdk.models.safety import PackageSafetyBlocker, _public_text_is_redaction_safe


def _require_selected_result(judgment: MatchedVariantJudgment, evaluation: EvaluationReceiptV2) -> None:
    """Retained results must describe the selected-case expected-signal route."""
    result = evaluation.case_results[0]
    judge = judgment.evidence.judge
    if (
        result.runner_id != judge.adapter_id
        or result.runner_version_or_digest != judge.adapter_version_or_digest
        or result.expected_output_sha256 is not None
        or result.output_digest_mismatch
    ):
        raise ValueError("matched result requires its actual judge runner and expected-signal oracle")
    public_values = (*result.evidence_refs, *result.missing_signals, *result.forbidden_commands_observed)
    if any(value != value.strip() or not _public_text_is_redaction_safe(value) for value in public_values):
        raise ValueError("matched result evidence must be normalized and public")


class MatchedExecutedPair(_MatchedContractModel):
    """One case/trial observed independently against both candidate variants."""

    case_id: str
    trial_index: int = Field(ge=0, strict=True)
    baseline: MatchedVariantJudgment
    candidate: MatchedVariantJudgment
    baseline_evaluation: EvaluationReceiptV2
    candidate_evaluation: EvaluationReceiptV2
    baseline_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MatchedExecutionReceipt(_MatchedContractModel):
    """Observed callbacks are not authenticated provider or promotion evidence."""

    schema_version: Literal["matched-execution/v1"] = "matched-execution/v1"
    plan: MatchedComparisonPlan | None = None
    lane: Literal["local", "cloud"] | None = None
    status: Literal["completed", "blocked"]
    calibrations: tuple[MatchedVariantCalibrationBundle, ...] = Field(default=(), max_length=2)
    pairs: tuple[MatchedExecutedPair, ...] = Field(default=(), max_length=60)
    provider_invocation_count: int = Field(ge=0, le=128, strict=True)
    judge_invocation_count: int = Field(ge=0, le=128, strict=True)
    elapsed_seconds: float = Field(ge=0, strict=True, allow_inf_nan=False)
    blocker: PackageSafetyBlocker | None = None
    evidence_scope: Literal["observed_adapter_callbacks"] = "observed_adapter_callbacks"
    external_authenticity_verified: Literal[False] = False
    promotion_authorized: Literal[False] = False

    _ingress_work_limit: ClassVar[int] = 3000000

    @field_validator("external_authenticity_verified", "promotion_authorized", mode="before")
    @classmethod
    def false_only(cls, value: object) -> object:
        if value is not False:
            raise ValueError("matched execution cannot claim authenticity or authorise promotion")
        return value

    @model_validator(mode="after")
    def observations_match_declared_prefix(self) -> MatchedExecutionReceipt:
        minimum = 2 * len(self.pairs)
        if not minimum <= self.judge_invocation_count <= self.provider_invocation_count:
            raise ValueError("matched observations require actual provider then judge coverage")
        if self.provider_invocation_count > minimum + 2:
            raise ValueError("first-stop matched execution can retain at most one unfinished pair")
        if self.provider_invocation_count == minimum + 2 and self.judge_invocation_count < minimum + 1:
            raise ValueError("candidate provider requires the preceding baseline judge invocation")
        if self.plan is None or self.lane is None:
            if self.status != "blocked" or self.pairs or self.provider_invocation_count or self.calibrations:
                raise ValueError("unbound matched receipt requires a pre-execution blocker")
        else:
            specification = next(item for item in self.plan.lanes if item.lane == self.lane)
            _require_budget_evidence(self, specification)
            if self.calibrations:
                if len(self.calibrations) != 2:
                    raise ValueError("matched receipt requires both frozen calibrations")
                for variant, receipt in zip(("baseline", "candidate"), self.calibrations, strict=True):
                    _require_variant_calibration(self.plan, specification, variant, receipt)
            elif self.provider_invocation_count:
                raise ValueError("matched invocations require retained calibration evidence")
            expected = [
                (binding.case_id, trial)
                for binding in self.plan.case_bindings
                for trial in range(specification.generator_parameters.trial_count)
            ]
            if len(self.pairs) > len(expected) or self.provider_invocation_count > 2 * len(expected):
                raise ValueError("matched execution cannot exceed its declared coverage")
            for pair, (case_id, trial) in zip(self.pairs, expected[: len(self.pairs)], strict=True):
                if (pair.case_id, pair.trial_index) != (case_id, trial):
                    raise ValueError("matched execution must retain its ordered case/trial prefix")
                binding = next(item for item in self.plan.case_bindings if item.case_id == case_id)
                if (
                    pair.baseline_input_sha256 != binding.baseline_input_sha256
                    or pair.candidate_input_sha256 != binding.candidate_input_sha256
                ):
                    raise ValueError("matched observations require the frozen variant input digests")
                _matched_pair_values(self.plan, self.lane, pair.baseline, pair.candidate)
                for judgment, evaluation in (
                    (pair.baseline, pair.baseline_evaluation),
                    (pair.candidate, pair.candidate_evaluation),
                ):
                    if (
                        evaluation.status == "blocked"
                        or evaluation.candidate != judgment.evidence.candidate
                        or evaluation.provider != judgment.evidence.provider
                        or evaluation.scenario_set_id != judgment.evidence.scenario_set_id
                        or evaluation.scorer.pass_threshold != 1.0
                        or evaluation.scorer.scorer_id != "selected-case-deterministic-v1"
                        or evaluation.scorer.version_or_digest != "selected-case-v1"
                        or not evaluation.scorer.deterministic_checks_first
                        or evaluation.scorer.calibration_required
                        or evaluation.scorer.calibration_probe_ids
                        or evaluation.completed_calibration_probe_ids
                        or len(evaluation.case_results) != 1
                        or evaluation.case_results[0].case_id != pair.case_id
                        or evaluation.case_results[0].observation_sha256 != judgment.evidence.output_sha256
                    ):
                        raise ValueError("matched pair requires the bound selected-case evaluation receipt")
                    if judgment.evidence.case_id != pair.case_id:
                        raise ValueError("matched pair must retain judgments for its declared case")
                    _require_selected_result(judgment, evaluation)
                    _dimension_score(self.plan.rubric, judgment)
                    if judgment.evidence.judge_result_sha256 != _dimension_digest(self.plan.rubric, judgment):
                        raise ValueError("matched execution requires complete rubric-bound judgments")
                    references = tuple(
                        ref for ref in judgment.evidence.evidence_refs if ref.startswith("judge-results/")
                    )
                    if references != (f"judge-results/{judgment.evidence.judge_result_sha256}",):
                        raise ValueError("matched execution requires its bound dimensional result reference")
            if self.status == "completed" and (
                len(self.pairs) != len(expected) or self.judge_invocation_count != 2 * len(expected)
            ):
                raise ValueError("completed matched lane requires all declared pairs and invocations")
        if self.status == "blocked":
            if self.blocker is None:
                raise ValueError("blocked matched execution requires a typed blocker")
            if self.blocker.code in {
                "invalid_matched_execution",
                "matched_cost_budget_unavailable",
                "matched_run_budget_insufficient",
                "matched_plugin_safety_evidence_required",
                "matched_plugin_safety_rejected",
            }:
                if self.pairs or self.calibrations or self.provider_invocation_count:
                    raise ValueError("input blocker cannot retain completed matched observations")
                if self.elapsed_seconds != 0.0:
                    raise ValueError("input blocker cannot claim callback elapsed time")
            elif self.blocker.code in {
                "matched_execution_incomplete",
                "matched_plugin_source_changed",
                "matched_plugin_safety_changed",
                "matched_time_budget_exhausted",
                "matched_provider_budget_exhausted",
                "matched_judge_budget_exhausted",
            }:
                if (
                    self.plan is None
                    or self.lane is None
                    or len(self.calibrations) != 2
                    or len(self.pairs) == len(expected)
                ):
                    raise ValueError("execution blocker requires an unfinished bound batch")
            else:
                raise ValueError("matched blocker must describe its retained evidence")
        elif self.blocker is not None or len(self.calibrations) != 2:
            raise ValueError("completed matched execution requires both calibrations and no blocker")
        return self

    @property
    def summary(self) -> MatchedLaneSummary | None:
        """Recompute descriptive selection only for a completed ten-case lane."""
        if self.status != "completed" or self.plan is None:
            return None
        ranks = {"low": 0, "medium": 1, "high": 2}
        observations = []
        for binding in self.plan.case_bindings:
            indexes = [index for index, pair in enumerate(self.pairs) if pair.case_id == binding.case_id]
            observations.append(
                (
                    binding.case_id,
                    tuple(
                        float(
                            _matched_weighted_score(self.pairs[index].candidate, self.plan.rubric)
                            - _matched_weighted_score(self.pairs[index].baseline, self.plan.rubric)
                        )
                        for index in indexes
                    ),
                    tuple(
                        min(ranks[self.pairs[index].baseline.confidence], ranks[self.pairs[index].candidate.confidence])
                        >= ranks[self.plan.rubric.minimum_confidence]
                        for index in indexes
                    ),
                )
            )
        return build_matched_lane_summary(
            tuple(observations),
            policy=self.plan.selection_policy,
            minimum_normalized_delta=self.plan.rubric.minimum_normalized_delta,
        )

    @property
    def requires_regression(self) -> bool:
        """Failing candidate checks or within-model decline require feedback closure."""
        return any(
            pair.candidate_evaluation.status != "pass"
            or any(item.status != "pass" for item in pair.candidate_evaluation.case_results)
            or self.comparison(index).regression_required
            for index, pair in enumerate(self.pairs)
        )

    def comparison(self, index: int) -> MatchedPairAssessment:
        """Recompute one retained within-model comparison, never a cross-model score."""
        if self.plan is None or self.lane is None:
            raise ValueError("matched receipt has no bound comparison")
        pair = self.pairs[index]
        left, right, decision = _matched_pair_values(self.plan, self.lane, pair.baseline, pair.candidate)
        return MatchedPairAssessment(
            plan=self.plan,
            lane=self.lane,
            status="assessed",
            baseline=pair.baseline,
            candidate=pair.candidate,
            baseline_score=left,
            candidate_score=right,
            normalized_delta=right - left,
            decision=decision,
            regression_required=right < left,
        )


def _require_budget_evidence(receipt: MatchedExecutionReceipt, specification: MatchedLaneSpec) -> None:
    budget = specification.budget
    code = receipt.blocker.code if receipt.blocker is not None else None
    if (
        receipt.provider_invocation_count > budget.maximum_provider_invocations
        or receipt.judge_invocation_count > budget.maximum_judge_invocations
    ):
        raise ValueError("matched observations cannot exceed their callback budgets")
    if code == "matched_cost_budget_unavailable" and budget.maximum_reported_cost is None:
        raise ValueError("cost-budget blocker requires an actual requested cost bound")
    if budget.maximum_reported_cost is not None and code not in {
        "matched_cost_budget_unavailable",
        "invalid_matched_execution",
    }:
        raise ValueError("unsupported cost budgets cannot admit callbacks")
    required = specification.generator_parameters.trial_count * 20
    if (
        code == "matched_run_budget_insufficient"
        and min(budget.maximum_provider_invocations, budget.maximum_judge_invocations) >= required
    ):
        raise ValueError("run-budget blocker requires inadequate declared coverage")
    if code == "matched_time_budget_exhausted" and receipt.elapsed_seconds < budget.maximum_elapsed_seconds:
        raise ValueError("time-budget blocker requires the elapsed admission deadline")
    if receipt.status == "completed" and receipt.elapsed_seconds >= budget.maximum_elapsed_seconds:
        raise ValueError("completed execution cannot exceed its elapsed admission budget")
    if (
        code == "matched_provider_budget_exhausted"
        and receipt.provider_invocation_count != budget.maximum_provider_invocations
    ):
        raise ValueError("provider-budget blocker requires exhausted callback allowance")
    if code == "matched_judge_budget_exhausted" and receipt.judge_invocation_count != budget.maximum_judge_invocations:
        raise ValueError("judge-budget blocker requires exhausted callback allowance")
