"""Fresh capabilities per trial, zero-access rejection and corrected-input recovery."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from test_matched_calibration import _dimensions
from test_matched_comparison import _plan
from test_observed_calibration import _batch, _repeat_trials

from skills_sdk.evaluation import CalibrationTrialAdapters, execute_matched_calibration, execute_scorer_calibration
from skills_sdk.models.observed_calibration import ObservedCalibrationPlan


def _close_after_use(adapter: object, method: str, events: list[str]) -> None:
    original = getattr(adapter, method)
    cleanup = adapter.cleanup
    closed = False

    async def invoke(*args: object) -> object:
        if closed:
            raise ValueError("capability was already closed")
        events.append(method)
        return await original(*args)

    async def close() -> None:
        nonlocal closed
        assert not closed
        closed = True
        events.append("close")
        await cleanup()

    setattr(adapter, method, invoke)
    adapter.cleanup = close


def _numeric(root: Path) -> tuple[object, tuple[object, ...]]:
    plan, batch, _ = _batch(root)
    raw = plan.model_dump(mode="json")
    raw["parameters"]["trial_count"] = 2
    plan = ObservedCalibrationPlan.model_validate(raw)
    return plan, _repeat_trials(plan, batch)


@pytest.mark.parametrize("dimensional", [False, True])
def test_fresh_stateful_trials_close_once(tmp_path: Path, dimensional: bool) -> None:
    if dimensional:
        plan, batch, _ = _dimensions(tmp_path, trials=2)
    else:
        plan, batch = _numeric(tmp_path)
    events: list[str] = []
    for item in batch:
        for pair in (CalibrationTrialAdapters(item.provider, item.judge), *item.trial_adapters):
            _close_after_use(pair.provider, "complete", events)
            _close_after_use(pair.judge, "judge", events)
    result = asyncio.run(
        execute_matched_calibration(plan, _plan().rubric, batch)
        if dimensional
        else execute_scorer_calibration(plan, batch)
    )
    assert result.status == "pass"
    observed = result.calibration if dimensional else result
    assert len(observed.results) == len(batch) * 2
    assert observed.judge_invocation_count == len(batch) * 2
    assert events.count("complete") == events.count("judge") == len(batch) * 2
    assert events.count("close") == len(batch) * 4


@pytest.mark.parametrize("dimensional", [False, True])
@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "list",
        "pair_type",
        "provider_alias",
        "judge_alias",
        "cross_role",
        "missing_provider",
        "missing_judge",
    ],
)
def test_bad_schedule_rejects_without_capability_access_and_recovers(
    tmp_path: Path, dimensional: bool, problem: str
) -> None:
    if dimensional:
        plan, batch, events = _dimensions(tmp_path, trials=2)
    else:
        plan, batch = _numeric(tmp_path)
        events = batch[0].judge.events

    class Unreadable:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"unexpected capability access: {name}")

    first, last = batch[0], batch[-1]
    pair = last.trial_adapters[0]
    missing_provider = object.__new__(CalibrationTrialAdapters)
    object.__setattr__(missing_provider, "judge", pair.judge)
    missing_judge = object.__new__(CalibrationTrialAdapters)
    object.__setattr__(missing_judge, "provider", pair.provider)
    changes = {
        "missing": (),
        "list": [pair],
        "pair_type": (object(),),
        "provider_alias": (replace(pair, provider=first.provider),),
        "judge_alias": (replace(pair, judge=first.judge),),
        "cross_role": (replace(pair, judge=first.provider),),
        "missing_provider": (missing_provider,),
        "missing_judge": (missing_judge,),
    }
    broken = (*batch[:-1], replace(last, trial_adapters=changes[problem]))
    # A separate unused capability proves schedule admission precedes metadata.
    broken = (replace(broken[0], judge=Unreadable()), *broken[1:]) if problem != "judge_alias" else broken
    result = asyncio.run(
        execute_matched_calibration(plan, _plan().rubric, broken)
        if dimensional
        else execute_scorer_calibration(plan, broken)
    )
    assert result.status == "blocked"
    assert events == []
    recovered = asyncio.run(
        execute_matched_calibration(plan, _plan().rubric, batch)
        if dimensional
        else execute_scorer_calibration(plan, batch)
    )
    assert recovered.status == "pass"


@pytest.mark.parametrize("dimensional", [False, True])
@pytest.mark.parametrize("failure", ["settings", "identity", "cancel", "cleanup"])
def test_later_trial_failure_retains_prefix_and_recovers(tmp_path: Path, dimensional: bool, failure: str) -> None:
    if dimensional:
        plan, batch, _ = _dimensions(tmp_path, trials=2)
    else:
        plan, batch = _numeric(tmp_path)
    judge = batch[0].trial_adapters[0].judge
    original = (judge.identity, judge.parameters, judge.judge, judge.cleanup)

    async def cancel(inputs: object) -> object:
        raise asyncio.CancelledError()

    async def malformed_cleanup() -> object:
        return False

    if failure == "settings":
        judge.parameters = judge.parameters.model_copy(update={"temperature": 0.5})
    elif failure == "identity":
        judge.identity = judge.identity.model_copy(update={"model_id": "different-model"})
    elif failure == "cancel":
        judge.judge = cancel
    else:
        judge.cleanup = malformed_cleanup
    result = asyncio.run(
        execute_matched_calibration(plan, _plan().rubric, batch)
        if dimensional
        else execute_scorer_calibration(plan, batch)
    )
    observed = result.calibration if dimensional else result
    assert result.status == "blocked"
    assert len(observed.results) == 1
    assert observed.judge_invocation_count == (1 if failure in {"settings", "identity"} else 2)
    if dimensional:
        assert len(result.judgments) == 1
    judge.identity, judge.parameters, judge.judge, judge.cleanup = original
    recovered = asyncio.run(
        execute_matched_calibration(plan, _plan().rubric, batch)
        if dimensional
        else execute_scorer_calibration(plan, batch)
    )
    assert recovered.status == "pass"
