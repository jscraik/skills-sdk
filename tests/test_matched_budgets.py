"""Matched runtime callback-budget admission, accounting and recovery."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation import matched_execution as service
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from tests.test_matched_execution import _matched


class Clock:
    """Provide a deterministic monotonic clock advanced only by test callbacks."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        """Return the controlled monotonic reading."""
        return self.value


def _budgeted(plan: MatchedComparisonPlan, **updates: object) -> MatchedComparisonPlan:
    """Replace the local lane budget through the public model boundary."""
    raw = plan.model_dump(mode="json")
    local = next(item for item in raw["lanes"] if item["lane"] == "local")
    local["budget"].update(updates)
    return MatchedComparisonPlan.model_validate(raw)


def test_exact_declared_callback_budget_completes_with_elapsed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allow exactly the required provider and judge calls and retain elapsed time."""
    plan, calibrations, batch, events = _matched(tmp_path)
    plan = _budgeted(plan, maximum_provider_invocations=40, maximum_judge_invocations=40)
    clock = Clock(12.0)
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=clock))
    result = asyncio.run(service.execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "completed" and result.elapsed_seconds == 0.0
    assert result.provider_invocation_count == result.judge_invocation_count == 40
    assert events.count("provider") == events.count("dimensional_judge") == 40


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"maximum_provider_invocations": 39}, "matched_run_budget_insufficient"),
        ({"maximum_judge_invocations": 39}, "matched_run_budget_insufficient"),
        (
            {"maximum_reported_cost": "1.00", "currency": "GBP"},
            "matched_cost_budget_unavailable",
        ),
    ],
)
def test_insufficient_or_cost_budget_blocks_before_capability_access_and_recovers(
    tmp_path: Path, updates: dict[str, object], code: str
) -> None:
    """Retain the typed preflight problem with zero callbacks and accept corrected input."""
    plan, calibrations, batch, events = _matched(tmp_path)
    blocked = asyncio.run(service.execute_matched_lane(_budgeted(plan, **updates), "local", calibrations, batch))
    assert blocked.status == "blocked" and blocked.blocker is not None and blocked.blocker.code == code
    assert blocked.provider_invocation_count == blocked.judge_invocation_count == 0
    assert blocked.elapsed_seconds == 0.0 and not events
    corrected = asyncio.run(service.execute_matched_lane(plan, "local", calibrations, batch))
    assert corrected.status == "completed"


def test_elapsed_budget_before_first_callback_preserves_zero_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Block a future provider call when elapsed time expires after admission."""
    plan, calibrations, batch, events = _matched(tmp_path)
    plan = _budgeted(plan, maximum_elapsed_seconds=1.0)
    readings = iter((0.0, 2.0, 2.0, 2.0))
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: next(readings, 2.0)))
    result = asyncio.run(service.execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "blocked" and result.blocker is not None
    assert result.blocker.code == "matched_time_budget_exhausted"
    assert result.provider_invocation_count == result.judge_invocation_count == 0
    assert result.elapsed_seconds == 2.0 and events == ["provider_cleanup"]


def test_slow_provider_stops_before_judge_and_still_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Count a completed slow provider attempt, run cleanup and prevent later callbacks."""
    plan, calibrations, batch, events = _matched(tmp_path)
    plan = _budgeted(plan, maximum_elapsed_seconds=1.0)
    clock = Clock()
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=clock))
    provider = batch[0].baseline.provider
    original = provider.complete

    async def slow(request: object, payload: object) -> object:
        """Advance controlled time only after the actual provider callback returns."""
        result = await original(request, payload)
        clock.value = 2.0
        return result

    provider.complete = slow
    result = asyncio.run(service.execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "blocked" and result.blocker is not None
    assert result.blocker.code == "matched_time_budget_exhausted" and not result.pairs
    assert result.provider_invocation_count == 1 and result.judge_invocation_count == 0
    assert events == ["provider", "provider_cleanup"]
    provider.complete = original
    clock.value = 0.0
    assert asyncio.run(service.execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


def test_slow_judge_retains_actual_attempts_cleanup_and_completed_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop after a slow judge callback without starting the candidate or later pairs."""
    plan, calibrations, batch, events = _matched(tmp_path)
    plan = _budgeted(plan, maximum_elapsed_seconds=1.0)
    clock = Clock()
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=clock))
    judge = batch[0].baseline.judge
    original = judge.judge

    async def slow(inputs: object) -> object:
        """Advance controlled time only after the actual judge callback returns."""
        result = await original(inputs)
        clock.value = 2.0
        return result

    judge.judge = slow
    result = asyncio.run(service.execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "blocked" and result.blocker is not None
    assert result.blocker.code == "matched_time_budget_exhausted" and not result.pairs
    assert result.provider_invocation_count == result.judge_invocation_count == 1
    assert events == ["provider", "provider_cleanup", "dimensional_judge", "dimensional_cleanup"]
    judge.judge = original
    clock.value = 0.0
    assert asyncio.run(service.execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


def test_runtime_counter_codes_only_increment_actual_delegate_calls() -> None:
    """Reject provider and judge attempts beyond exact limits without incrementing them."""
    raw = {
        "maximum_provider_invocations": 1,
        "maximum_judge_invocations": 1,
        "maximum_elapsed_seconds": 10.0,
    }
    limits = service.MatchedRunBudget.model_validate(raw)
    budget = service._RuntimeBudget(limits, service.time.monotonic())
    budget.begin("provider")
    with pytest.raises(ContractError, match="matched_provider_budget_exhausted"):
        budget.begin("provider")
    assert budget.provider_invocations == 1
    budget.blocker_code = None
    budget.begin("judge")
    with pytest.raises(ContractError, match="matched_judge_budget_exhausted"):
        budget.begin("judge")
    assert budget.judge_invocations == 1


def test_final_cleanup_deadline_is_typed_blocker_and_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)
    plan = _budgeted(plan, maximum_elapsed_seconds=1.0)
    clock = Clock()
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=clock))
    judge = batch[-1].candidate.additional_trials[-1].judge
    original = judge.cleanup

    async def slow_cleanup() -> None:
        await original()
        clock.value = 2.0

    judge.cleanup = slow_cleanup
    result = asyncio.run(service.execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "blocked" and result.blocker.code == "matched_time_budget_exhausted"
    assert result.elapsed_seconds == 2.0 and len(result.pairs) == 19
    assert result.provider_invocation_count == result.judge_invocation_count == 40
    assert events.count("dimensional_cleanup") == 40
    judge.cleanup = original
    clock.value = 0.0
    assert asyncio.run(service.execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"
