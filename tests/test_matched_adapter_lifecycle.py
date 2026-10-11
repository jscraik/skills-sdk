"""Repeated trials use fresh capabilities without changing single-call cleanup."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from test_matched_execution import _matched

from skills_sdk.evaluation import MatchedTrialAdapters, execute_matched_lane
from skills_sdk.evaluation.matched_admission import preflight_matched_lane


class ClosingProvider:
    """Model a transport whose cleanup permanently closes its session."""

    def __init__(self, delegate: object, *, cleanup_failure: bool = False) -> None:
        self.delegate = delegate
        self.descriptor, self.parameters = delegate.descriptor, delegate.parameters
        self.closed, self.calls, self.cleanups = False, 0, 0
        self.cleanup_failure = cleanup_failure

    async def complete(self, request: object, payload: object) -> object:
        assert not self.closed, "provider was reused after cleanup"
        self.calls += 1
        return await self.delegate.complete(request, payload)

    async def cleanup(self) -> None:
        self.closed = True
        self.cleanups += 1
        if self.cleanup_failure:
            raise RuntimeError("fixture cleanup failure")
        await self.delegate.cleanup()


class ClosingJudge:
    """Model a judge session that must not receive calls after cleanup."""

    def __init__(self, delegate: object) -> None:
        self.delegate = delegate
        self.identity, self.parameters = delegate.identity, delegate.parameters
        self.closed, self.calls, self.cleanups = False, 0, 0

    async def judge(self, inputs: object) -> object:
        assert not self.closed, "judge was reused after cleanup"
        self.calls += 1
        return await self.delegate.judge(inputs)

    async def cleanup(self) -> None:
        self.closed = True
        self.cleanups += 1
        await self.delegate.cleanup()


@pytest.mark.parametrize("role", ["provider", "judge"])
def test_closing_first_trial_adapter_is_not_reused(tmp_path: Path, role: str) -> None:
    plan, calibrations, batch, _events = _matched(tmp_path)
    adapter_type = ClosingProvider if role == "provider" else ClosingJudge
    adapter = adapter_type(getattr(batch[0].baseline, role))
    first = replace(batch[0], baseline=replace(batch[0].baseline, **{role: adapter}))
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, (first, *batch[1:])))
    assert receipt.status == "completed"
    assert receipt.provider_invocation_count == receipt.judge_invocation_count == 40
    assert len(receipt.pairs) == 20
    assert adapter.calls == adapter.cleanups == 1 and adapter.closed


def test_every_trial_closes_its_own_provider_and_judge(tmp_path: Path) -> None:
    plan, calibrations, batch, _events = _matched(tmp_path)
    adapters = []

    def wrap(item: object) -> object:
        first = MatchedTrialAdapters(ClosingProvider(item.provider), ClosingJudge(item.judge))
        additional = tuple(
            MatchedTrialAdapters(ClosingProvider(trial.provider), ClosingJudge(trial.judge))
            for trial in item.additional_trials
        )
        adapters.extend((first, *additional))
        return replace(item, provider=first.provider, judge=first.judge, additional_trials=additional)

    observed = tuple(replace(pair, baseline=wrap(pair.baseline), candidate=wrap(pair.candidate)) for pair in batch)
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, observed))
    assert receipt.status == "completed" and len(adapters) == 40
    for trial in adapters:
        for adapter in (trial.provider, trial.judge):
            assert adapter.calls == adapter.cleanups == 1 and adapter.closed


@pytest.mark.parametrize("mutation", ["missing", "extra", "list", "mapping", "trial", "case", "role"])
def test_malformed_or_reused_schedule_rejects_without_host_access(tmp_path: Path, mutation: str) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)

    class HostTrap:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"unexpected host access: {name}")

    first = batch[0].baseline
    extra = MatchedTrialAdapters(HostTrap(), HostTrap())
    if mutation == "missing":
        additional = ()
    elif mutation == "extra":
        additional = (extra, extra)
    elif mutation == "list":
        additional = [extra]
    elif mutation == "mapping":
        additional = ({"provider": HostTrap(), "judge": HostTrap()},)
    elif mutation == "trial":
        additional = (MatchedTrialAdapters(first.provider, first.judge),)
    elif mutation == "case":
        additional = (MatchedTrialAdapters(batch[-1].candidate.provider, HostTrap()),)
    else:
        additional = (MatchedTrialAdapters(extra.provider, extra.provider),)
    first = replace(first, additional_trials=additional)
    broken = (replace(batch[0], baseline=first), *batch[1:])
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, broken))
    assert result.status == "blocked" and result.blocker.code == "invalid_matched_execution"
    assert result.provider_invocation_count == result.judge_invocation_count == 0 and not events
    assert preflight_matched_lane(plan, "local", calibrations, batch) is None


def test_cleanup_failure_stops_before_later_trial_and_fresh_schedule_recovers(tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)
    first = batch[0].baseline
    broken_provider = ClosingProvider(first.provider, cleanup_failure=True)
    later = ClosingProvider(first.additional_trials[0].provider)
    broken = replace(
        first,
        provider=broken_provider,
        additional_trials=(replace(first.additional_trials[0], provider=later),),
    )
    receipt = asyncio.run(
        execute_matched_lane(plan, "local", calibrations, (replace(batch[0], baseline=broken), *batch[1:]))
    )
    assert receipt.status == "blocked" and receipt.blocker.code == "matched_execution_incomplete"
    assert receipt.provider_invocation_count == 1 and receipt.judge_invocation_count == 0 and not receipt.pairs
    assert broken_provider.calls == broken_provider.cleanups == 1
    assert later.calls == later.cleanups == 0 and not later.closed
    events.clear()
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


@pytest.mark.parametrize("mutation", ["empty", "reuse", "pair"])
def test_callback_cannot_replace_the_admitted_later_capabilities(tmp_path: Path, mutation: str) -> None:
    plan, calibrations, batch, _events = _matched(tmp_path)
    original = batch[0].baseline
    later = ClosingProvider(original.additional_trials[0].provider)
    first = replace(original, additional_trials=(replace(original.additional_trials[0], provider=later),))

    class MutatingProvider(ClosingProvider):
        async def complete(self, request: object, payload: object) -> object:
            result = await super().complete(request, payload)
            if mutation == "empty":
                object.__setattr__(first, "additional_trials", ())
            elif mutation == "reuse":
                object.__setattr__(first.additional_trials[0], "provider", self)
            else:
                object.__setattr__(supplied_pair, "baseline", original)
            return result

    current = MutatingProvider(first.provider)
    first = replace(first, provider=current)
    supplied_pair = replace(batch[0], baseline=first)
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, (supplied_pair, *batch[1:])))
    assert receipt.status == "completed"
    assert current.calls == current.cleanups == later.calls == later.cleanups == 1


def test_cancellation_cleans_current_adapter_and_leaves_unused_trials_untouched(tmp_path: Path) -> None:
    plan, calibrations, batch, _events = _matched(tmp_path)

    async def run() -> None:
        entered = asyncio.Event()

        class PendingProvider(ClosingProvider):
            async def complete(self, request: object, payload: object) -> object:
                self.calls += 1
                entered.set()
                await asyncio.Event().wait()

        first = batch[0].baseline
        current = PendingProvider(first.provider)
        later = ClosingProvider(first.additional_trials[0].provider)
        pending = replace(
            first, provider=current, additional_trials=(replace(first.additional_trials[0], provider=later),)
        )
        task = asyncio.create_task(
            execute_matched_lane(plan, "local", calibrations, (replace(batch[0], baseline=pending), *batch[1:]))
        )
        await asyncio.wait_for(entered.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert current.calls == current.cleanups == 1 and current.closed
        assert later.calls == later.cleanups == 0 and not later.closed

    asyncio.run(run())


@pytest.mark.parametrize("role", ["provider", "judge"])
@pytest.mark.parametrize("result", [False, {"not": "a cleanup result"}])
def test_malformed_cleanup_return_blocks_then_valid_adapters_recover(tmp_path: Path, role: str, result: object) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)
    parent = ClosingProvider if role == "provider" else ClosingJudge

    class BadCleanup(parent):
        async def cleanup(self) -> object:
            await super().cleanup()
            return result

    first = batch[0].baseline
    adapter = BadCleanup(getattr(first, role))
    broken = replace(batch[0], baseline=replace(first, **{role: adapter}))
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, (broken, *batch[1:])))
    assert receipt.status == "blocked" and receipt.blocker.code == "matched_execution_incomplete"
    assert receipt.provider_invocation_count == 1
    assert receipt.judge_invocation_count == (0 if role == "provider" else 1)
    assert not receipt.pairs and adapter.calls == adapter.cleanups == 1
    events.clear()
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"
