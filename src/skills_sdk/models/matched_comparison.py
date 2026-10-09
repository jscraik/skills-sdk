"""Matched comparison inputs and supplied judgment assessment contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.evaluation_v2 import ScenarioSetV2
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256
from skills_sdk.models.matched_ingress import _MatchedContractModel
from skills_sdk.models.matched_plugin_scope import MatchedPluginScope
from skills_sdk.models.matched_policy import MatchedRunBudget, MatchedSelectionPolicy
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.safety import PackageSafetyBlocker, _public_text_is_redaction_safe
from skills_sdk.models.scorer_quality import ScorerJudgeParameters
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence


class _MatchedPublicModel(_MatchedContractModel):
    @field_validator("*", mode="before")
    @classmethod
    def public_strings_are_normalized(cls, value: object) -> object:
        if isinstance(value, str) and (value != value.strip() or not _public_text_is_redaction_safe(value)):
            raise ValueError("matched public text must be normalized and redacted")
        return value


class MatchedRubricDimension(_MatchedPublicModel):
    """One hidden scoring criterion with a frozen positive weight."""

    dimension_id: NonEmptyText
    criterion: NonEmptyText
    weight: float = Field(gt=0, le=1, strict=True, allow_inf_nan=False)


class MatchedComparisonRubric(_MatchedPublicModel):
    """Versioned dimensions and winner policy, stable across both model lanes."""

    rubric_id: NonEmptyText
    version_or_digest: NonEmptyText
    dimensions: tuple[MatchedRubricDimension, ...] = Field(min_length=1, max_length=16)
    minimum_normalized_delta: float = Field(gt=0, le=1, strict=True, allow_inf_nan=False)
    minimum_confidence: Literal["medium", "high"] = "medium"

    @model_validator(mode="after")
    def dimensions_are_normalized(self) -> MatchedComparisonRubric:
        ids = tuple(item.dimension_id for item in self.dimensions)
        if len(ids) != len(set(ids)) or sum(Decimal(str(item.weight)) for item in self.dimensions) != Decimal(1):
            raise ValueError("matched rubric requires unique dimensions with weights totaling one")
        return self


class MatchedCaseBinding(_MatchedPublicModel):
    """Bind the same hidden assertions to each visible case in both variants."""

    case_id: NonEmptyText
    baseline_scenario_set_id: NonEmptyText
    candidate_scenario_set_id: NonEmptyText
    assertion_contract_sha256: Sha256
    check_contract_sha256: Sha256
    baseline_input_sha256: Sha256
    candidate_input_sha256: Sha256
    semantic_signal_ids: tuple[NonEmptyText, ...]

    @field_validator("semantic_signal_ids")
    @classmethod
    def semantic_ids_are_public(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(
            value != value.strip() or not _public_text_is_redaction_safe(value) for value in values
        ):
            raise ValueError("matched semantic signal IDs must be unique and public")
        return values


class MatchedLaneSpec(_MatchedContractModel):
    """Actual model identities/settings, not a discovered host profile name."""

    lane: Literal["local", "cloud"]
    generator: ProviderIdentityV2
    generator_parameters: ScorerJudgeParameters
    judge: ProviderIdentityV2
    judge_parameters: ScorerJudgeParameters
    baseline_calibration_sha256: Sha256
    candidate_calibration_sha256: Sha256
    budget: MatchedRunBudget

    @model_validator(mode="after")
    def settings_bind_models(self) -> MatchedLaneSpec:
        if (
            self.generator_parameters.model != self.generator.model_id
            or self.judge_parameters.model != self.judge.model_id
        ):
            raise ValueError("matched settings must bind their actual models")
        if self.generator_parameters.trial_count != self.judge_parameters.trial_count:
            raise ValueError("matched generator and judge trial coverage must agree")
        return self


class MatchedComparisonPlan(_MatchedContractModel):
    """Freeze two variants, ten cases, calibrated lanes and one hidden rubric."""

    schema_version: Literal["matched-comparison-plan/v1"] = "matched-comparison-plan/v1"
    plugin_scope: MatchedPluginScope
    baseline_scenarios: tuple[ScenarioSetV2, ...] = Field(min_length=10, max_length=10)
    candidate_scenarios: tuple[ScenarioSetV2, ...] = Field(min_length=10, max_length=10)
    case_bindings: tuple[MatchedCaseBinding, ...] = Field(min_length=10, max_length=10)
    rubric: MatchedComparisonRubric
    lanes: tuple[MatchedLaneSpec, ...] = Field(min_length=2, max_length=2)
    selection_policy: MatchedSelectionPolicy

    _ingress_work_limit: ClassVar[int] = 1048576

    @property
    def baseline(self) -> PackageCandidateIdentity:
        """Expose the complete baseline plugin identity, never a child alias."""
        assert self.plugin_scope.baseline.candidate is not None
        return self.plugin_scope.baseline.candidate

    @property
    def candidate(self) -> PackageCandidateIdentity:
        """Expose the complete candidate plugin identity, including every captured file."""
        assert self.plugin_scope.candidate.candidate is not None
        return self.plugin_scope.candidate.candidate

    @model_validator(mode="after")
    def variants_are_matched(self) -> MatchedComparisonPlan:
        for scope, binding, left, right in zip(
            self.plugin_scope.cases, self.case_bindings, self.baseline_scenarios, self.candidate_scenarios, strict=True
        ):
            if len(left.cases) != 1 or len(right.cases) != 1 or left.cases != right.cases:
                raise ValueError("matched variants require identical singleton child scenarios")
            case = left.cases[0]
            if scope.case_id != binding.case_id or case.case_id != binding.case_id:
                raise ValueError("matched scope, scenarios and hidden bindings must follow the same active order")
            for scenarios, scorer, identifier in (
                (left, scope.baseline_scorer, binding.baseline_scenario_set_id),
                (right, scope.candidate_scorer, binding.candidate_scenario_set_id),
            ):
                if (
                    scenarios.candidate != scorer.candidate
                    or scenarios.scenario_set_id != identifier
                    or scenarios.release
                ):
                    raise ValueError("matched singleton scenario must bind its selected child and case identity")
                public = (scorer.scorer_id, scorer.version_or_digest, scenarios.scenario_set_id)
                if any(value != value.strip() or not _public_text_is_redaction_safe(value) for value in public):
                    raise ValueError("matched child and scorer identifiers must be public")
            if not set(binding.semantic_signal_ids) <= set(case.expected_signals):
                raise ValueError("matched semantic signals must belong to their frozen scenario")
        if not any(item.cases[0].category == "regression" for item in self.baseline_scenarios):
            raise ValueError("managed matched coverage requires a regression case")
        if tuple(item.lane for item in self.lanes) != ("local", "cloud"):
            raise ValueError("matched lanes must declare local before cloud")
        if sum(item.generator_parameters.trial_count * 20 for item in self.lanes) > 128:
            raise ValueError("matched comparison exceeds its execution budget")
        return self

    @property
    def digest(self) -> str:
        """Include every frozen case, model, setting and rubric in experiment identity."""
        return canonical_json_sha256(self.model_dump(mode="json"))


class MatchedDimensionJudgment(_MatchedPublicModel):
    """One supplied numeric dimension with a public rationale and evidence."""

    dimension_id: NonEmptyText
    score: float = Field(ge=0, le=5, strict=True, allow_inf_nan=False)
    rationale: NonEmptyText
    evidence_refs: tuple[PortablePath, ...] = Field(min_length=1)

    @field_validator("rationale")
    @classmethod
    def rationale_is_public(cls, value: str) -> str:
        if not _public_text_is_redaction_safe(value):
            raise ValueError("matched rationale must not retain private data")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def references_are_public(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("matched evidence references must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not _public_text_is_redaction_safe(value):
                raise ValueError("matched evidence references must not retain private data")
        return values


class MatchedVariantJudgment(_MatchedContractModel):
    """Digest-bound evidence supplied for one variant, never invocation proof."""

    evidence: SelectedCaseJudgeEvidence
    dimensions: tuple[MatchedDimensionJudgment, ...] = Field(min_length=1, max_length=16)
    confidence: Literal["low", "medium", "high"]


class MatchedPairAssessment(_MatchedContractModel):
    """Recomputed comparison of supplied judgments; no executed-lane claim."""

    schema_version: Literal["matched-pair-assessment/v1"] = "matched-pair-assessment/v1"
    plan: MatchedComparisonPlan | None = None
    lane: Literal["local", "cloud"] | None
    status: Literal["assessed", "blocked"]
    baseline: MatchedVariantJudgment | None = None
    candidate: MatchedVariantJudgment | None = None
    baseline_score: float | None = Field(default=None, ge=0, le=1, strict=True, allow_inf_nan=False)
    candidate_score: float | None = Field(default=None, ge=0, le=1, strict=True, allow_inf_nan=False)
    normalized_delta: float | None = Field(default=None, ge=-1, le=1, strict=True, allow_inf_nan=False)
    decision: Literal["baseline", "candidate", "inconclusive"] | None = None
    regression_required: bool = Field(default=False, strict=True)
    blocker: PackageSafetyBlocker | None = None
    execution_performed: Literal[False] = False
    promotion_authorized: Literal[False] = False

    @field_validator("execution_performed", "promotion_authorized", mode="before")
    @classmethod
    def false_only(cls, value: object) -> object:
        if value is not False:
            raise ValueError("supplied matched assessments cannot claim execution or promotion")
        return value

    @model_validator(mode="after")
    def assessment_matches_evidence(self) -> MatchedPairAssessment:
        if self.status == "blocked":
            if self.blocker is None or self.blocker.code != "invalid_matched_judgments":
                raise ValueError("blocked matched assessment requires its input blocker")
            if (
                any(
                    value is not None
                    for value in (
                        self.baseline,
                        self.candidate,
                        self.baseline_score,
                        self.candidate_score,
                        self.normalized_delta,
                        self.decision,
                    )
                )
                or self.regression_required
            ):
                raise ValueError("blocked matched assessment cannot retain completed decisions")
            return self
        if self.plan is None or self.baseline is None or self.candidate is None or self.blocker is not None:
            raise ValueError("matched assessment requires both judgments and a plan")
        if self.lane is None:
            raise ValueError("assessed matched evidence requires a declared lane")
        baseline_score, candidate_score, decision = _matched_pair_values(
            self.plan, self.lane, self.baseline, self.candidate
        )
        if (
            self.baseline_score,
            self.candidate_score,
            self.normalized_delta,
            self.decision,
            self.regression_required,
        ) != (
            baseline_score,
            candidate_score,
            candidate_score - baseline_score,
            decision,
            candidate_score < baseline_score,
        ):
            raise ValueError("matched decision must equal its complete dimensional evidence")
        return self


def _matched_weighted_score(judgment: MatchedVariantJudgment, rubric: MatchedComparisonRubric) -> Decimal:
    return sum(
        Decimal(str(row.score)) * Decimal(str(dimension.weight))
        for row, dimension in zip(judgment.dimensions, rubric.dimensions, strict=True)
    ) / Decimal(5)


def _matched_pair_values(
    plan: MatchedComparisonPlan,
    lane: Literal["local", "cloud"],
    baseline: MatchedVariantJudgment,
    candidate: MatchedVariantJudgment,
) -> tuple[float, float, Literal["baseline", "candidate", "inconclusive"]]:
    """Bind supplied judgments and recompute within-model scores and tie policy."""
    specification = next((item for item in plan.lanes if item.lane == lane), None)
    if specification is None:
        raise ValueError("matched judgments require a declared lane")
    case_id = baseline.evidence.case_id
    binding = next((item for item in plan.case_bindings if item.case_id == case_id), None)
    if binding is None or candidate.evidence.case_id != case_id:
        raise ValueError("matched judgments must cover one declared identical case")
    scores = []
    scope = next(item for item in plan.plugin_scope.cases if item.case_id == case_id)
    for identity, scenario_set_id, judgment in (
        (scope.baseline_scorer.candidate, binding.baseline_scenario_set_id, baseline),
        (scope.candidate_scorer.candidate, binding.candidate_scenario_set_id, candidate),
    ):
        evidence = judgment.evidence
        if not set(evidence.satisfied_assertion_ids) <= set(binding.semantic_signal_ids):
            raise ValueError("matched judgment contains undeclared semantic assertions")
        if (
            evidence.candidate != identity
            or evidence.scenario_set_id != scenario_set_id
            or evidence.provider != specification.generator
            or evidence.judge != specification.judge
            or evidence.assertion_contract_sha256 != binding.assertion_contract_sha256
        ):
            raise ValueError("matched judgment identity or hidden criteria drifted")
        if tuple(item.dimension_id for item in judgment.dimensions) != tuple(
            item.dimension_id for item in plan.rubric.dimensions
        ):
            raise ValueError("matched judgments require each frozen dimension exactly once")
        if any(not set(row.evidence_refs).issubset(evidence.evidence_refs) for row in judgment.dimensions):
            raise ValueError("matched dimensions must reference retained judge evidence")
        scores.append(_matched_weighted_score(judgment, plan.rubric))
    baseline_score, candidate_score = (float(value) for value in scores)
    ranks = {"low": 0, "medium": 1, "high": 2}
    if min(ranks[baseline.confidence], ranks[candidate.confidence]) < ranks[plan.rubric.minimum_confidence]:
        return baseline_score, candidate_score, "inconclusive"
    delta = scores[1] - scores[0]
    if abs(delta) < Decimal(str(plan.rubric.minimum_normalized_delta)) or delta == 0:
        return baseline_score, candidate_score, "inconclusive"
    return baseline_score, candidate_score, "candidate" if delta > 0 else "baseline"
