"""Whole-batch matched execution admission without accessing host capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.live_selected_case import SelectedCaseJudgeAdapter
from skills_sdk.evaluation.matched_plugin_context import PluginExecutionContext, _request_matches_plugin_context
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput, assess_pre_execution_safety
from skills_sdk.evaluation.selected_case import (
    SelectedCaseDefinition,
    _revalidate_definition,
)
from skills_sdk.models.matched_comparison import MatchedComparisonPlan, MatchedLaneSpec
from skills_sdk.models.matched_ingress import _canonical_matched_input
from skills_sdk.models.matched_plugin_calibration import _require_variant_calibration
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.safety import PackageSafetyBlocker
from skills_sdk.providers.call import TextProviderAdapter


@dataclass(frozen=True, slots=True)
class MatchedVariantExecution:
    """Private execution capabilities retained outside portable receipt models."""

    definition: SelectedCaseDefinition
    request: ProviderExecutionRequest
    inputs: SelectedCaseExecutionInput
    provider: TextProviderAdapter
    judge: SelectedCaseJudgeAdapter
    plugin_context: PluginExecutionContext | None = None


@dataclass(frozen=True, slots=True)
class MatchedCaseExecution:
    """One ordered active case executed independently against both variants."""

    baseline: MatchedVariantExecution
    candidate: MatchedVariantExecution


def _require_calibration(plan: MatchedComparisonPlan, lane: MatchedLaneSpec, variant: str, raw: object) -> None:
    _require_variant_calibration(plan, lane, variant, raw)


def _require_variant(
    plan: MatchedComparisonPlan, lane: MatchedLaneSpec, index: int, variant: str, item: MatchedVariantExecution
) -> None:
    if type(item) is not MatchedVariantExecution or type(item.inputs) is not SelectedCaseExecutionInput:
        raise ValueError("matched execution requires explicit private capabilities")
    definition = _revalidate_definition(item.definition)
    request = ProviderExecutionRequest.model_validate(_canonical_matched_input(item.request))
    expected = (plan.baseline_scenarios if variant == "baseline" else plan.candidate_scenarios)[index]
    scope = plan.plugin_scope.cases[index]
    binding = plan.case_bindings[index]
    expected_input = binding.baseline_input_sha256 if variant == "baseline" else binding.candidate_input_sha256
    expected_set_id = binding.baseline_scenario_set_id if variant == "baseline" else binding.candidate_scenario_set_id
    if (
        definition.scenario_set.candidate != expected.candidate
        or definition.scenario_set.scenario_set_id != expected_set_id
        or definition.scenario_set.cases != expected.cases
        or definition.assertion_contract_sha256 != plan.case_bindings[index].assertion_contract_sha256
        or definition.check_contract_sha256 != binding.check_contract_sha256
        or definition.semantic_signal_ids != binding.semantic_signal_ids
        or request.provider != lane.generator
        or request.input_sha256 != expected_input
    ):
        raise ValueError("matched execution case, candidate, assertions or generator changed")
    context = item.plugin_context
    if (
        type(context) is not PluginExecutionContext
        or context.validation != getattr(plan.plugin_scope, variant)
        or context.driver_skill_path != scope.driver_skill_path
        or context.selected_skill_paths != scope.selected_skill_paths
        or context.reference_paths != scope.reference_paths
    ):
        raise ValueError("matched execution requires its exact whole-plugin case context")
    if not _request_matches_plugin_context(definition, request, item.inputs.payload, context):
        raise ValueError("matched execution request does not bind the complete plugin context")
    blocker = assess_pre_execution_safety(request, item.inputs.safety_evidence, package_root=definition._package_root)
    if blocker is not None:
        raise ValueError("matched execution requires current source-bound safety")
    _require_plugin_safety(item)


def _require_plugin_safety(item: MatchedVariantExecution) -> None:
    """Keep whole-plugin safety proof independent from the selected child's review."""
    from skills_sdk.evaluation.plugin_safety import assess_plugin_pre_execution_safety
    from skills_sdk.models.plugin_safety import PluginPreExecutionSafetyEvidence

    context = item.plugin_context
    if type(context) is not PluginExecutionContext or context.safety_evidence is None:
        raise ContractError("matched_plugin_safety_evidence_required", "Whole-plugin safety evidence is required.")
    try:
        evidence = PluginPreExecutionSafetyEvidence.model_validate(context.safety_evidence)
        if evidence.validation != context.validation:
            raise ValueError("matched plugin safety must bind the complete frozen capture")
    except (AttributeError, TypeError, ValueError, RecursionError):
        raise ContractError("matched_plugin_safety_rejected", "Whole-plugin safety evidence is invalid.") from None
    blocker = assess_plugin_pre_execution_safety(context.root, evidence, policy=context.policy)
    if blocker is not None:
        raise ContractError("matched_plugin_safety_rejected", "Whole-plugin safety evidence failed current assessment.")


def preflight_matched_lane(
    plan: object, lane: str, calibrations: tuple[object, object], executions: tuple[MatchedCaseExecution, ...]
) -> PackageSafetyBlocker | None:
    """Validate supplied commitments and the entire batch before host property access.

    Receipt validation binds supplied callback observations, not external judge
    authenticity. Success here is admission only and never execution proof.
    """
    try:
        parsed = MatchedComparisonPlan.model_validate(plan)
        specification = next((item for item in parsed.lanes if item.lane == lane), None)
        if specification is None or type(calibrations) is not tuple or len(calibrations) != 2:
            raise ValueError("matched lane and both calibrations are required")
        budget = specification.budget
        if budget.maximum_reported_cost is not None:
            return PackageSafetyBlocker(
                code="matched_cost_budget_unavailable",
                message="Matched adapters do not supply cost observations; requested cost limits cannot be enforced.",
            )
        required = specification.generator_parameters.trial_count * 20
        if min(budget.maximum_provider_invocations, budget.maximum_judge_invocations) < required:
            return PackageSafetyBlocker(
                code="matched_run_budget_insufficient",
                message="The declared callback budget cannot cover all frozen case trials.",
            )
        for variant, receipt in zip(("baseline", "candidate"), calibrations, strict=True):
            _require_calibration(parsed, specification, variant, receipt)
        if type(executions) is not tuple or len(executions) != 10:
            raise ValueError("matched execution must cover all ten active cases")
        for index, pair in enumerate(executions):
            if type(pair) is not MatchedCaseExecution:
                raise ValueError("matched execution requires paired capabilities")
            _require_variant(parsed, specification, index, "baseline", pair.baseline)
            _require_variant(parsed, specification, index, "candidate", pair.candidate)
    except ContractError as error:
        if error.code in {"matched_plugin_safety_evidence_required", "matched_plugin_safety_rejected"}:
            return PackageSafetyBlocker(
                code=error.code, message="Matched execution requires current whole-plugin safety."
            )
        return PackageSafetyBlocker(code="invalid_matched_execution", message="Matched source input is invalid.")
    except (AttributeError, TypeError, ValueError):
        return PackageSafetyBlocker(
            code="invalid_matched_execution",
            message="Matched execution requires a complete source-bound calibrated batch.",
        )
    return None
