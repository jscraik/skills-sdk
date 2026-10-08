"""Execute held-out numeric calibration through the existing guarded judge lane."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.live_selected_case import (
    SelectedCaseJudgeAdapter,
    SelectedCaseJudgeInput,
    execute_selected_case_with_judge,
)
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput, assess_pre_execution_safety
from skills_sdk.evaluation.selected_case import (
    SelectedCaseDefinition,
    _request_matches_definition,
    _revalidate_definition,
)
from skills_sdk.models.observed_calibration import (
    CalibrationJudgeVerdict,
    HeldOutCalibrationProbe,
    ObservedCalibrationPlan,
    ObservedCalibrationProbeResult,
    ObservedCalibrationReceipt,
)
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.safety import PackageSafetyBlocker
from skills_sdk.models.scorer_quality import ScorerJudgeParameters
from skills_sdk.providers.call import TextProviderAdapter


@dataclass(frozen=True, slots=True)
class CalibrationProbeExecution:
    """Private adapter capabilities; none are serialised into calibration receipts."""

    definition: SelectedCaseDefinition
    request: ProviderExecutionRequest
    inputs: SelectedCaseExecutionInput
    provider: TextProviderAdapter
    judge: SelectedCaseJudgeAdapter


class _CalibrationJudge:
    def __init__(
        self,
        delegate: SelectedCaseJudgeAdapter,
        plan: ObservedCalibrationPlan,
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
        parameters = ScorerJudgeParameters.model_validate(
            ObservedCalibrationPlan.normalize_nested_models(raw_parameters)
        )
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
        await self.delegate.cleanup()


def _blocked(
    code: str,
    plan: ObservedCalibrationPlan | None,
    results: tuple[ObservedCalibrationProbeResult, ...] = (),
    invocation_count: int = 0,
) -> ObservedCalibrationReceipt:
    return ObservedCalibrationReceipt(
        plan=plan,
        status="blocked",
        results=results,
        judge_execution_performed=invocation_count > 0,
        judge_invocation_count=invocation_count,
        blocker=PackageSafetyBlocker(
            code=code, message="Observed calibration requires complete bound execution evidence."
        ),
    )


def _preflight(plan: ObservedCalibrationPlan, executions: tuple[CalibrationProbeExecution, ...]) -> str | None:
    """Validate the whole batch before accessing any host capability properties."""
    if type(executions) is not tuple or len(executions) != len(plan.probes):
        return "calibration_execution_coverage"
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
    parsed: ObservedCalibrationPlan | None = None
    try:
        parsed = ObservedCalibrationPlan.model_validate(plan)
        problem = _preflight(parsed, executions)
    except (AttributeError, TypeError, ValueError, ContractError):
        return _blocked("invalid_calibration_input", parsed)
    if problem is not None:
        return _blocked(problem, parsed)
    results: list[ObservedCalibrationProbeResult] = []
    invocation_count = 0
    expanded = [
        (probe, item, trial)
        for probe, item in zip(parsed.probes, executions, strict=True)
        for trial in range(parsed.parameters.trial_count)
    ]
    for probe, item, trial in expanded:
        frame = _CalibrationJudge(item.judge, parsed, probe, trial)
        try:
            evaluation = await execute_selected_case_with_judge(
                item.definition, item.request, item.inputs, item.provider, frame
            )
        except (AttributeError, TypeError, ValueError, ContractError):
            return _blocked(
                "calibration_execution_failed", parsed, tuple(results), invocation_count + int(frame.invoked)
            )
        invocation_count += int(frame.invoked)
        if evaluation.status == "blocked" or frame.result is None:
            return _blocked("calibration_execution_incomplete", parsed, tuple(results), invocation_count)
        results.append(frame.result)
    try:
        return ObservedCalibrationReceipt(
            plan=parsed,
            status="pass",
            results=tuple(results),
            judge_execution_performed=True,
            judge_invocation_count=invocation_count,
        )
    except ValidationError:
        return _blocked("calibration_policy_failed", parsed, tuple(results), invocation_count)
