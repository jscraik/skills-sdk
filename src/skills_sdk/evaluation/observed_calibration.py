"""Execute held-out numeric calibration through the existing guarded judge lane."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.live_selected_case import (
    SelectedCaseJudgeAdapter,
    SelectedCaseJudgeInput,
    _judge_bindings,
    execute_selected_case_with_judge,
)
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput, assess_pre_execution_safety
from skills_sdk.evaluation.selected_case import (
    SelectedCaseDefinition,
    _request_matches_definition,
    _revalidate_definition,
)
from skills_sdk.models.native_judge import CodexNativeJudgeParameters
from skills_sdk.models.observed_calibration import (
    CalibrationJudgeVerdict,
    HeldOutCalibrationProbe,
    NativeCalibrationPlan,
    NativeCalibrationReceipt,
    ObservedCalibrationPlan,
    ObservedCalibrationProbeResult,
    ObservedCalibrationReceipt,
)
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.safety import PackageSafetyBlocker
from skills_sdk.models.scorer_quality import ScorerJudgeParameters
from skills_sdk.providers.call import TextProviderAdapter
from skills_sdk.providers.codex_judge import CodexCalibrationJudgeAdapter, CodexJudgeAdapter


@dataclass(frozen=True, slots=True)
class CalibrationTrialAdapters:
    """One trial's independently owned provider and judge capabilities."""

    provider: TextProviderAdapter
    judge: SelectedCaseJudgeAdapter


@dataclass(frozen=True, slots=True)
class CalibrationProbeExecution:
    """Private adapter capabilities; none are serialised into calibration receipts."""

    definition: SelectedCaseDefinition
    request: ProviderExecutionRequest
    inputs: SelectedCaseExecutionInput
    provider: TextProviderAdapter
    judge: SelectedCaseJudgeAdapter
    trial_adapters: tuple[CalibrationTrialAdapters, ...] = ()


def _trial_schedule(item: CalibrationProbeExecution) -> tuple[CalibrationTrialAdapters, ...]:
    """Return the initial adapter pair followed by the explicit later-trial pairs."""
    return (CalibrationTrialAdapters(item.provider, item.judge), *item.trial_adapters)


def _capability_schedule_problem(
    plan: ObservedCalibrationPlan | NativeCalibrationPlan, executions: tuple[CalibrationProbeExecution, ...]
) -> str | None:
    """Reject missing or aliased capabilities without reading adapter properties."""
    if type(executions) is not tuple or len(executions) != len(plan.probes):
        return "calibration_execution_coverage"
    seen: set[int] = set()
    for item in executions:
        if type(item) is not CalibrationProbeExecution:
            return "invalid_calibration_execution"
        if type(item.trial_adapters) is not tuple or len(item.trial_adapters) != plan.parameters.trial_count - 1:
            return "calibration_trial_coverage"
        if any(type(pair) is not CalibrationTrialAdapters for pair in item.trial_adapters):
            return "invalid_calibration_execution"
        for pair in _trial_schedule(item):
            for capability in (pair.provider, pair.judge):
                owner = capability
                if issubclass(type(capability), CodexCalibrationJudgeAdapter):
                    if type(capability) is not CodexCalibrationJudgeAdapter:
                        return "invalid_calibration_execution"
                    owner = CodexCalibrationJudgeAdapter.capability_owner(capability)
                    if not issubclass(type(owner), CodexJudgeAdapter):
                        return "invalid_calibration_execution"
                if owner is None or id(owner) in seen:
                    return "calibration_capability_reuse"
                seen.add(id(owner))
            if type(plan) is NativeCalibrationPlan and issubclass(type(pair.judge), CodexJudgeAdapter):
                return "invalid_calibration_execution"
    return None


class _CalibrationJudge:
    """Bind one judge invocation to held-out probe evidence and trial settings."""

    def __init__(
        self,
        delegate: SelectedCaseJudgeAdapter,
        plan: ObservedCalibrationPlan | NativeCalibrationPlan,
        probe: HeldOutCalibrationProbe,
        trial: int,
    ) -> None:
        self.delegate = delegate
        self.plan = plan
        self.probe = probe
        self.trial = trial
        self.result: ObservedCalibrationProbeResult | None = None
        self.invoked = False

    @property
    def identity(self) -> ProviderIdentityV2:
        """Check actual adapter identity/settings only after the executor safety gate."""
        identity = ProviderIdentityV2.model_validate(
            ObservedCalibrationPlan.normalize_nested_models(self.delegate.identity)
        )
        raw_parameters = getattr(self.delegate, "parameters", None)
        parameter_model = (
            CodexNativeJudgeParameters if type(self.plan) is NativeCalibrationPlan else ScorerJudgeParameters
        )
        parameters = parameter_model.model_validate(ObservedCalibrationPlan.normalize_nested_models(raw_parameters))
        if identity != self.plan.judge or parameters != self.plan.parameters:
            raise ValueError("calibration judge identity or settings drifted")
        return identity

    async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
        """Keep labels in this harness; delegate receives only ordinary judge input."""
        if inputs.output_sha256 != self.probe.output_sha256:
            raise ValueError("held-out output drifted")
        callback = self.delegate.judge
        if not callable(callback):
            raise ValueError("calibration judge callback is not callable")
        identity_before = self.identity
        self.invoked = True
        raw = await callback(inputs)
        if self.identity != identity_before:
            raise ValueError("calibration judge identity drifted during invocation")
        verdict = CalibrationJudgeVerdict.model_validate(raw)
        self.result = ObservedCalibrationProbeResult(
            probe_id=self.probe.probe_id,
            trial_index=self.trial,
            output_sha256=inputs.output_sha256,
            expected_label=self.probe.expected_label,
            predicted_label="pass" if verdict.score >= self.plan.policy.threshold else "fail",
            score=verdict.score,
            judge_result_sha256=canonical_json_sha256(verdict.model_dump(mode="json")),
        )
        return verdict.evidence

    async def cleanup(self) -> None:
        """Reuse the executor's bounded cleanup lifecycle."""
        if await self.delegate.cleanup() is not None:
            raise ValueError("calibration judge cleanup must resolve to None")


def _blocked(
    code: str,
    plan: ObservedCalibrationPlan | NativeCalibrationPlan | None,
    results: tuple[ObservedCalibrationProbeResult, ...] = (),
    invocation_count: int = 0,
    native: bool = False,
) -> ObservedCalibrationReceipt | NativeCalibrationReceipt:
    receipt_model = NativeCalibrationReceipt if native else ObservedCalibrationReceipt
    return receipt_model(
        plan=plan,
        status="blocked",
        results=results,
        judge_execution_performed=invocation_count > 0,
        judge_invocation_count=invocation_count,
        blocker=PackageSafetyBlocker(
            code=code, message="Observed calibration requires complete bound execution evidence."
        ),
    )


def _preflight(
    plan: ObservedCalibrationPlan | NativeCalibrationPlan, executions: tuple[CalibrationProbeExecution, ...]
) -> str | None:
    """Validate the whole batch before accessing any host capability properties."""
    problem = _capability_schedule_problem(plan, executions)
    if problem is not None:
        return problem
    for item in executions:
        if type(item) is not CalibrationProbeExecution or type(item.inputs) is not SelectedCaseExecutionInput:
            return "invalid_calibration_execution"
        definition = _revalidate_definition(item.definition)
        request = ProviderExecutionRequest.model_validate(ObservedCalibrationPlan.normalize_nested_models(item.request))
        if (
            definition.scenario_set.candidate != plan.candidate
            or request.candidate != plan.candidate
            or definition.assertion_contract_sha256 != plan.assertion_contract_sha256
        ):
            return "calibration_candidate_or_rubric_mismatch"
        if canonical_json_sha256(item.inputs.payload) != request.input_sha256:
            return "calibration_input_mismatch"
        if not _request_matches_definition(definition, request, item.inputs.payload):
            return "calibration_request_mismatch"
        blocker = assess_pre_execution_safety(
            request, item.inputs.safety_evidence, package_root=definition._package_root
        )
        if blocker is not None:
            return blocker.code
    return None


async def execute_scorer_calibration(
    plan: object, executions: tuple[CalibrationProbeExecution, ...]
) -> ObservedCalibrationReceipt:
    """Observe numeric judgments, then enforce held-out coverage and error policy.

    Adapters may be controlled offline implementations. Invocation is observed,
    not external authenticity; no receipt from this route authorises promotion.
    """
    result = await _execute_calibration(plan, executions, native=False)
    assert type(result) is ObservedCalibrationReceipt
    return result


async def execute_native_calibration(
    plan: object, executions: tuple[CalibrationProbeExecution, ...]
) -> NativeCalibrationReceipt:
    """Execute explicit native adapters through the same safety and first-stop gates."""
    result = await _execute_calibration(plan, executions, native=True)
    assert type(result) is NativeCalibrationReceipt
    return result


async def _execute_calibration(
    plan: object, executions: tuple[CalibrationProbeExecution, ...], *, native: bool
) -> ObservedCalibrationReceipt | NativeCalibrationReceipt:
    parsed: ObservedCalibrationPlan | NativeCalibrationPlan | None = None
    plan_model = NativeCalibrationPlan if native else ObservedCalibrationPlan
    receipt_model = NativeCalibrationReceipt if native else ObservedCalibrationReceipt
    try:
        parsed = plan_model.model_validate(plan)
        problem = _preflight(parsed, executions)
    except (AttributeError, TypeError, ValueError, ContractError):
        return _blocked("invalid_calibration_input", parsed, native=native)
    if problem is not None:
        return _blocked(problem, parsed, native=native)
    if native:
        for probe, item in zip(parsed.probes, executions, strict=True):
            for trial, adapters in enumerate(_trial_schedule(item)):
                if await _judge_bindings(adapters.judge) is None:
                    return _blocked("invalid_calibration_input", parsed, native=True)
                if type(adapters.judge) is CodexCalibrationJudgeAdapter:
                    owner = CodexCalibrationJudgeAdapter.capability_owner(adapters.judge)
                    if await _judge_bindings(owner) is None:
                        return _blocked("invalid_calibration_input", parsed, native=True)
                frame = _CalibrationJudge(adapters.judge, parsed, probe, trial)
                if await _judge_bindings(frame) is None:
                    return _blocked("invalid_calibration_input", parsed, native=True)
    results: list[ObservedCalibrationProbeResult] = []
    invocation_count = 0
    expanded = [
        (probe, item, trial, adapters)
        for probe, item in zip(parsed.probes, executions, strict=True)
        for trial, adapters in enumerate(_trial_schedule(item))
    ]
    for probe, item, trial, adapters in expanded:
        frame = _CalibrationJudge(adapters.judge, parsed, probe, trial)
        try:
            evaluation = await execute_selected_case_with_judge(
                item.definition, item.request, item.inputs, adapters.provider, frame
            )
        except (AttributeError, TypeError, ValueError, ContractError):
            return _blocked(
                "calibration_execution_failed", parsed, tuple(results), invocation_count + int(frame.invoked), native
            )
        invocation_count += int(frame.invoked)
        if evaluation.status == "blocked" or frame.result is None:
            return _blocked("calibration_execution_incomplete", parsed, tuple(results), invocation_count, native)
        results.append(frame.result)
    try:
        return receipt_model(
            plan=parsed,
            status="pass",
            results=tuple(results),
            judge_execution_performed=True,
            judge_invocation_count=invocation_count,
        )
    except ValidationError:
        return _blocked("calibration_policy_failed", parsed, tuple(results), invocation_count, native)
