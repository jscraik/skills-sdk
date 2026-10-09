"""Observed two-variant execution through the existing bounded provider lifecycle."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import Literal

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.live_selected_case import SelectedCaseJudgeInput, _execute_selected_case_with_judge
from skills_sdk.evaluation.matched_admission import (
    MatchedCaseExecution,
    MatchedTrialAdapters,
    MatchedVariantExecution,
    _require_plugin_safety,
    preflight_matched_lane,
)
from skills_sdk.evaluation.matched_calibration import _DimensionalCalibrationJudge
from skills_sdk.evaluation.matched_plugin_context import _request_matches_plugin_context
from skills_sdk.evaluation.selected_case import SelectedCaseDefinition
from skills_sdk.models.matched_comparison import MatchedComparisonPlan, MatchedLaneSpec
from skills_sdk.models.matched_execution import MatchedExecutedPair, MatchedExecutionReceipt
from skills_sdk.models.matched_ingress import _canonical_matched_input
from skills_sdk.models.matched_plugin_calibration import MatchedVariantCalibrationBundle
from skills_sdk.models.matched_policy import MatchedRunBudget
from skills_sdk.models.matched_trial import matched_trial_identity
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.safety import PackageSafetyBlocker
from skills_sdk.models.scorer_quality import ScorerJudgeParameters
from skills_sdk.providers import JsonValue, ProviderAdapterComplete
from skills_sdk.providers.types import ProviderAdapterStreamItem


@dataclass(slots=True)
class _RuntimeBudget:
    """Track actual callback attempts and elapsed monotonic execution time."""

    limits: MatchedRunBudget
    started_at: float
    provider_invocations: int = 0
    judge_invocations: int = 0
    blocker_code: str | None = None

    def elapsed(self) -> float:
        """Return nonnegative elapsed monotonic time for the receipt."""
        return max(0.0, time.monotonic() - self.started_at)

    def _block(self, code: str) -> None:
        """Retain the first runtime exhaustion reason and stop the callback."""
        self.blocker_code = self.blocker_code or code
        raise ContractError(code=code, message="matched execution callback budget is exhausted")

    def begin(self, kind: Literal["provider", "judge"]) -> None:
        """Gate one future callback and count only the delegate call being attempted."""
        if self.elapsed() >= self.limits.maximum_elapsed_seconds:
            self._block("matched_time_budget_exhausted")
        if kind == "provider":
            if self.provider_invocations >= self.limits.maximum_provider_invocations:
                self._block("matched_provider_budget_exhausted")
            self.provider_invocations += 1
        else:
            if self.judge_invocations >= self.limits.maximum_judge_invocations:
                self._block("matched_judge_budget_exhausted")
            self.judge_invocations += 1

    def finish(self) -> float:
        """Reject a callback that completed after the elapsed-time boundary."""
        elapsed = self.elapsed()
        if elapsed >= self.limits.maximum_elapsed_seconds:
            self._block("matched_time_budget_exhausted")
        return elapsed


class _MatchedProvider:
    def __init__(
        self, delegate: object, specification: MatchedLaneSpec, budget: _RuntimeBudget, guard: _PluginGuard
    ) -> None:
        self.delegate, self.specification, self.budget, self.invocations = delegate, specification, budget, 0
        self.guard = guard
        self._stream_iterator: AsyncIterator[ProviderAdapterStreamItem] | None = None

    @property
    def descriptor(self) -> TextProviderAdapterDescriptor:
        self.guard.check()
        descriptor = TextProviderAdapterDescriptor.model_validate(_canonical_matched_input(self.delegate.descriptor))
        parameters = ScorerJudgeParameters.model_validate(_canonical_matched_input(self.delegate.parameters))
        if descriptor.provider != self.specification.generator or parameters != self.specification.generator_parameters:
            raise ValueError("matched generator identity or settings changed")
        return descriptor

    async def complete(self, request: object, input_payload: JsonValue) -> ProviderAdapterComplete:
        self.guard.check()
        before = self.descriptor
        callback = self.delegate.complete
        if not callable(callback):
            raise ValueError("matched generator callback is unavailable")
        self.guard.check()
        self.budget.begin("provider")
        self.invocations += 1
        result = await callback(request, input_payload)
        self.guard.check()
        self.budget.finish()
        if self.descriptor != before:
            raise ValueError("matched generator changed during its callback")
        return result

    async def cleanup(self) -> None:
        try:
            iterator, self._stream_iterator = self._stream_iterator, None
            close = getattr(iterator, "aclose", None)
            if callable(close):
                await close()
        finally:
            if await self.delegate.cleanup() is not None:
                raise ValueError("matched provider cleanup must resolve to None")

    async def stream(self, request: object, input_payload: JsonValue) -> AsyncIterator[ProviderAdapterStreamItem]:
        """Preserve descriptor-selected pull streaming with one counted invocation."""
        self.guard.check()
        before = self.descriptor
        callback = self.delegate.stream
        if not callable(callback):
            raise ValueError("matched generator stream callback is unavailable")
        self.guard.check()
        self.budget.begin("provider")
        self.invocations += 1
        iterator = await callback(request, input_payload)
        self._stream_iterator = iterator
        self.guard.check()
        self.budget.finish()
        if self.descriptor != before:
            raise ValueError("matched stream identity changed while opening")

        async def guarded() -> AsyncIterator[ProviderAdapterStreamItem]:
            """Guard each pull without buffering or consuming the stream eagerly."""
            while True:
                self.guard.check()
                self.budget.finish()
                if self.descriptor != before:
                    raise ValueError("matched stream identity changed before a pull")
                try:
                    value = await anext(iterator)
                except StopAsyncIteration:
                    return
                self.guard.check()
                self.budget.finish()
                if self.descriptor != before:
                    raise ValueError("matched stream identity changed during a pull")
                yield value

        return guarded()


class _BudgetedJudgeDelegate:
    """Place the shared guard immediately around the actual judge delegate call."""

    def __init__(self, delegate: object, budget: _RuntimeBudget, guard: _PluginGuard) -> None:
        self.delegate, self.budget = delegate, budget
        self.guard = guard

    @property
    def identity(self) -> object:
        return self.delegate.identity

    @property
    def parameters(self) -> object:
        return self.delegate.parameters

    async def judge(self, inputs: object) -> object:
        self.guard.check()
        callback = self.delegate.judge
        if not callable(callback):
            raise ValueError("matched judge callback is unavailable")
        self.guard.check()
        self.budget.begin("judge")
        result = await callback(inputs)
        self.guard.check()
        self.budget.finish()
        return result

    async def cleanup(self) -> None:
        if await self.delegate.cleanup() is not None:
            raise ValueError("matched judge cleanup must resolve to None")


class _MatchedJudge:
    def __init__(
        self,
        delegate: object,
        plan: MatchedComparisonPlan,
        specification: MatchedLaneSpec,
        budget: _RuntimeBudget,
        guard: _PluginGuard,
    ) -> None:
        self.delegate, self.specification, self.budget = delegate, specification, budget
        self.guard = guard
        self.dimensions = _DimensionalCalibrationJudge(_BudgetedJudgeDelegate(delegate, budget, guard), plan.rubric)

    @property
    def invocations(self) -> int:
        return self.dimensions.invocations

    @property
    def identity(self) -> ProviderIdentityV2:
        self.guard.check()
        identity = ProviderIdentityV2.model_validate(_canonical_matched_input(self.delegate.identity))
        parameters = ScorerJudgeParameters.model_validate(_canonical_matched_input(self.delegate.parameters))
        if identity != self.specification.judge or parameters != self.specification.judge_parameters:
            raise ValueError("matched judge identity or settings changed")
        return identity

    async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
        before = self.identity
        verdict = await self.dimensions.judge(inputs)
        if self.identity != before:
            raise ValueError("matched judge changed during its callback")
        return verdict.evidence

    async def cleanup(self) -> None:
        await self.dimensions.cleanup()


@dataclass(slots=True)
class _PluginGuard:
    """Recapture complete plugin source and safety at each private callback boundary."""

    item: MatchedVariantExecution
    blocker_code: str | None = None

    def _fail(self, code: str) -> None:
        self.blocker_code = self.blocker_code or code
        raise ContractError(code, "Matched execution requires unchanged plugin source and safety.")

    def matches(
        self, definition: SelectedCaseDefinition, request: ProviderExecutionRequest, payload: JsonValue
    ) -> bool:
        try:
            matched = _request_matches_plugin_context(definition, request, payload, self.item.plugin_context)
        except (AttributeError, TypeError, ValueError, ContractError):
            matched = False
        if not matched:
            self._fail("matched_plugin_source_changed")
        return True

    def check(self) -> None:
        self.matches(self.item.definition, self.item.request, self.item.inputs.payload)
        try:
            _require_plugin_safety(self.item)
        except (AttributeError, TypeError, ValueError, ContractError):
            self._fail("matched_plugin_safety_changed")


def _receipt(
    binding: tuple[
        MatchedComparisonPlan | None, Literal["local", "cloud"] | None, tuple[MatchedVariantCalibrationBundle, ...]
    ],
    pairs: list[MatchedExecutedPair],
    counts: tuple[int, int],
    code: str | None,
    elapsed_seconds: float = 0.0,
) -> MatchedExecutionReceipt:
    return MatchedExecutionReceipt(
        plan=binding[0],
        lane=binding[1],
        calibrations=binding[2],
        pairs=tuple(pairs),
        provider_invocation_count=counts[0],
        judge_invocation_count=counts[1],
        elapsed_seconds=elapsed_seconds,
        status="completed" if code is None else "blocked",
        blocker=None
        if code is None
        else PackageSafetyBlocker(code=code, message="Matched execution requires complete bound observations."),
    )


def _snapshot_executions(executions: tuple[MatchedCaseExecution, ...]) -> tuple[MatchedCaseExecution, ...]:
    """Retain admitted adapter references before any host callback can replace them."""

    def snapshot(item: MatchedVariantExecution) -> MatchedVariantExecution:
        return replace(
            item,
            additional_trials=tuple(
                MatchedTrialAdapters(trial.provider, trial.judge) for trial in item.additional_trials
            ),
        )

    return tuple(MatchedCaseExecution(snapshot(pair.baseline), snapshot(pair.candidate)) for pair in executions)


async def execute_matched_lane(
    plan: object, lane: str, calibrations: tuple[object, object], executions: tuple[MatchedCaseExecution, ...]
) -> MatchedExecutionReceipt:
    """Preflight the complete ten-case batch, then observe bounded paired callbacks.

    This route observes one model lane. It does not grant cloud handoff, registry
    admission or promotion; the local-before-cloud feedback route is separate.
    """
    parsed: MatchedComparisonPlan | None = None
    selected: Literal["local", "cloud"] | None = None
    try:
        parsed = MatchedComparisonPlan.model_validate(plan)
        if lane not in ("local", "cloud"):
            raise ValueError("matched lane is undeclared")
        selected = lane
        problem = preflight_matched_lane(parsed, lane, calibrations, executions)
        if problem is not None:
            return _receipt((parsed, selected, ()), [], (0, 0), problem.code)
        executions = _snapshot_executions(executions)
        retained = tuple(MatchedVariantCalibrationBundle.model_validate(item) for item in calibrations)
    except (TypeError, ValueError, ContractError):
        return _receipt((None, None, ()), [], (0, 0), "invalid_matched_execution")
    binding = (parsed, selected, retained)
    specification = next(item for item in parsed.lanes if item.lane == selected)
    budget = _RuntimeBudget(specification.budget, time.monotonic())
    plan_digest = parsed.digest
    pairs: list[MatchedExecutedPair] = []
    for pair in executions:
        for trial in range(specification.generator_parameters.trial_count):
            outcomes = []
            for variant, supplied_item in (("baseline", pair.baseline), ("candidate", pair.candidate)):
                request_id, idempotency = matched_trial_identity(
                    plan_digest, selected, supplied_item.request.case_id, variant, trial
                )
                request_data = supplied_item.request.model_dump(mode="json")
                request_data.update(request_id=request_id, idempotency_key_sha256=idempotency)
                item = replace(supplied_item, request=ProviderExecutionRequest.model_validate(request_data))
                if trial:
                    adapters = supplied_item.additional_trials[trial - 1]
                    item = replace(item, provider=adapters.provider, judge=adapters.judge)
                guard = _PluginGuard(item)
                provider, judge = (
                    _MatchedProvider(item.provider, specification, budget, guard),
                    _MatchedJudge(item.judge, parsed, specification, budget, guard),
                )
                try:
                    guard.check()
                    result = await _execute_selected_case_with_judge(
                        item.definition, item.request, item.inputs, provider, judge, guard.matches
                    )
                    guard.check()
                    elapsed_seconds = budget.finish()
                except (AttributeError, TypeError, ValueError, ContractError):
                    result = None
                if result is None or result.status == "blocked" or not judge.dimensions.judgments:
                    code = budget.blocker_code or guard.blocker_code or "matched_execution_incomplete"
                    return _receipt(
                        binding,
                        pairs,
                        (budget.provider_invocations, budget.judge_invocations),
                        code,
                        budget.elapsed(),
                    )
                outcomes.append((item, judge.dimensions.judgments[0], result))
            left, right = outcomes
            pair_guard = _PluginGuard(pair.baseline)
            try:
                pair_guard.check()
                pair_guard = _PluginGuard(pair.candidate)
                pair_guard.check()
                elapsed_seconds = budget.finish()
            except (AttributeError, TypeError, ValueError, ContractError):
                return _receipt(
                    binding,
                    pairs,
                    (budget.provider_invocations, budget.judge_invocations),
                    budget.blocker_code or pair_guard.blocker_code or "matched_execution_incomplete",
                    budget.elapsed(),
                )
            pairs.append(
                MatchedExecutedPair(
                    case_id=left[0].request.case_id,
                    trial_index=trial,
                    baseline=left[1],
                    candidate=right[1],
                    baseline_evaluation=left[2],
                    candidate_evaluation=right[2],
                    baseline_input_sha256=left[0].request.input_sha256,
                    candidate_input_sha256=right[0].request.input_sha256,
                    baseline_request=left[0].request,
                    candidate_request=right[0].request,
                )
            )
    return _receipt(
        binding,
        pairs,
        (budget.provider_invocations, budget.judge_invocations),
        None,
        elapsed_seconds,
    )
