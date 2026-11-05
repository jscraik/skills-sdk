from __future__ import annotations

import asyncio
import gc
import io
import weakref
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Literal

import pytest

from skills_sdk.providers import (
    ProviderAdapterChunk,
    ProviderAdapterComplete,
    ProviderAdapterStreamItem,
    ProviderAdapterTerminal,
    ProviderCallLimits,
    ProviderCallOutcome,
    execute_provider_call,
)
from skills_sdk.providers.types import AsyncioProviderCallClock
from tests.test_provider_call import FakeAdapter, _provider_request


async def _assert_caller_cancellation(
    task: asyncio.Task[ProviderCallOutcome], started: asyncio.Event, release: asyncio.Event
) -> None:
    """Bound phase entry and cancellation, releasing owned work even on failure."""
    phase = asyncio.create_task(started.wait())
    try:
        done, _ = await asyncio.wait({task, phase}, timeout=1, return_when=asyncio.FIRST_COMPLETED)
        assert phase in done and not task.done(), "provider call did not remain active at the expected phase"
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        assert task in done, "caller cancellation did not finish within the test deadline"
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        phase.cancel()
        task.cancel()
        done, _ = await asyncio.wait({task, phase}, timeout=1)
        assert done == {task, phase}, "owned test tasks did not finish during teardown"
        for owned in done:
            if not owned.cancelled():
                owned.exception()


def test_caller_cancellation_during_cleanup_is_not_swallowed() -> None:
    async def scenario() -> None:
        request = _provider_request(None)
        started, release = asyncio.Event(), asyncio.Event()

        class SlowCleanupAdapter(FakeAdapter):
            async def cleanup(self) -> None:
                self.cleanup_calls += 1
                started.set()
                await release.wait()

        adapter = SlowCleanupAdapter(request)
        task = asyncio.create_task(execute_provider_call(request, None, adapter))
        await _assert_caller_cancellation(task, started, release)
        assert adapter.cleanup_calls == 1

    asyncio.run(scenario())


def test_caller_cancellation_during_stalled_stream_stops_pulls_and_cleans_up() -> None:
    async def scenario() -> None:
        request = _provider_request(None)
        started, release = asyncio.Event(), asyncio.Event()

        class StalledStreamAdapter(FakeAdapter):
            async def _stalled(self) -> AsyncIterator[ProviderAdapterStreamItem]:
                self.stream_pulls += 1
                started.set()
                await release.wait()
                yield ProviderAdapterChunk("late")

            async def stream(self, request: object, input_payload: object) -> AsyncIterator[ProviderAdapterStreamItem]:
                return self._stalled()

        adapter = StalledStreamAdapter(request, mode="stream")
        task = asyncio.create_task(execute_provider_call(request, None, adapter))
        await _assert_caller_cancellation(task, started, release)
        assert adapter.stream_pulls == 1
        assert adapter.cleanup_calls == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["factory", "complete", "cleanup"])
def test_cancellation_resistant_hook_does_not_hold_receipt_past_deadline(
    phase: Literal["factory", "complete", "cleanup"],
) -> None:
    async def scenario() -> None:
        request = _provider_request(None)
        cancelled, release, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def stall() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()

        class Adapter(FakeAdapter):
            async def complete(self, request: object, input_payload: object) -> ProviderAdapterComplete:
                await stall()
                return ProviderAdapterComplete("late", ("evidence/complete",))

            async def stream(self, request: object, input_payload: object) -> AsyncIterator[ProviderAdapterStreamItem]:
                if phase == "factory":
                    await stall()
                return self.events()

            async def events(self) -> AsyncIterator[ProviderAdapterStreamItem]:
                yield ProviderAdapterTerminal(("evidence/stream",))

            async def cleanup(self) -> None:
                self.cleanup_calls += 1
                if phase == "cleanup":
                    await stall()
                cleaned.set()

        adapter = Adapter(request, mode="complete" if phase == "complete" else "stream")
        task = asyncio.create_task(
            execute_provider_call(
                request, None, adapter, limits=ProviderCallLimits(overall_seconds=0.02, cleanup_seconds=0.02)
            )
        )
        try:
            await asyncio.wait_for(cancelled.wait(), 1)
            done, _pending = await asyncio.wait({task}, timeout=0.2)
            returned_before_release = bool(done)
        finally:
            release.set()
        outcome = await asyncio.wait_for(task, 1)
        await asyncio.wait_for(cleaned.wait(), 1)
        assert returned_before_release, "receipt remained blocked by a cancellation-resistant hook"
        assert outcome.public_result.cleanup_succeeded is False
        assert outcome.public_result.cleanup_error_code == "cleanup_failed"
        assert adapter.cleanup_calls == 1
        if phase != "cleanup":
            assert outcome.public_result.execution.error is not None
            assert outcome.public_result.execution.error.code == "provider_call_timeout"
            assert outcome.complete_text is None
        else:
            assert outcome.public_result.status == "completed"

    asyncio.run(scenario())


@pytest.mark.parametrize("inherited", [False, True])
def test_default_clock_keeps_concurrent_call_cleanup_independent(inherited: bool) -> None:
    async def scenario() -> None:
        request = _provider_request(None)
        started, release = asyncio.Event(), asyncio.Event()

        class Clock(AsyncioProviderCallClock):
            def now(self) -> datetime:
                return datetime(2026, 9, 8, 10, 0, tzinfo=UTC)

        clock = Clock() if inherited else AsyncioProviderCallClock()

        class SlowAdapter(FakeAdapter):
            async def complete(self, request: object, input_payload: object) -> ProviderAdapterComplete:
                started.set()
                await release.wait()
                return ProviderAdapterComplete("slow", ("evidence/complete",))

        slow = SlowAdapter(request)
        fast = FakeAdapter(request)
        task = asyncio.create_task(execute_provider_call(request, None, slow, clock=clock))
        await asyncio.wait_for(started.wait(), 1)
        try:
            outcome = await asyncio.wait_for(execute_provider_call(request, None, fast, clock=clock), 0.2)
            assert outcome.public_result.cleanup_succeeded
            assert fast.cleanup_calls == 1
            assert slow.cleanup_calls == 0
            if inherited:
                assert outcome.public_result.execution.started_at == clock.now()
        finally:
            release.set()
            await task
        assert slow.cleanup_calls == 1

    asyncio.run(scenario())


def test_deferred_cleanup_remains_owned_after_receipt_and_garbage_collection() -> None:
    async def scenario() -> None:
        request = _provider_request(None)
        cancelled, cleaned = asyncio.Event(), asyncio.Event()
        waiters: list[weakref.ReferenceType[asyncio.Future[None]]] = []

        async def pause() -> None:
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            waiters.append(weakref.ref(waiter))
            await waiter

        class Adapter(FakeAdapter):
            async def cleanup(self) -> None:
                self.cleanup_calls += 1
                try:
                    await pause()
                except asyncio.CancelledError:
                    cancelled.set()
                    await pause()
                cleaned.set()

        adapter = Adapter(request)
        outcome = await execute_provider_call(request, None, adapter, limits=ProviderCallLimits(cleanup_seconds=0.01))
        await asyncio.wait_for(cancelled.wait(), 1)
        assert not outcome.public_result.cleanup_succeeded
        gc.collect()
        waiter = waiters[-1]()
        assert waiter is not None, "deferred cleanup task was garbage collected before completion"
        waiter.set_result(None)
        await asyncio.wait_for(cleaned.wait(), 1)
        assert adapter.cleanup_calls == 1

    asyncio.run(scenario())


def test_caller_cancellation_defers_resource_cleanup_until_stream_finalizer_finishes() -> None:
    async def scenario() -> None:
        request = _provider_request(None)
        started, finalizing, release, finished, cleaned = (asyncio.Event() for _ in range(5))
        buffer = io.StringIO()
        errors: list[str] = []

        class Adapter(FakeAdapter):
            async def stream(self, request: object, input_payload: object) -> AsyncIterator[ProviderAdapterStreamItem]:
                return self.events()

            async def events(self) -> AsyncIterator[ProviderAdapterStreamItem]:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    finalizing.set()
                    await release.wait()
                    try:
                        buffer.write("final record")
                    except ValueError as error:
                        errors.append(str(error))
                    finished.set()
                yield ProviderAdapterTerminal(("evidence/stream",))

            async def cleanup(self) -> None:
                self.cleanup_calls += 1
                buffer.close()
                cleaned.set()

        adapter = Adapter(request, mode="stream")
        task = asyncio.create_task(
            execute_provider_call(request, None, adapter, limits=ProviderCallLimits(cleanup_seconds=0.02))
        )
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        try:
            await asyncio.wait_for(finalizing.wait(), 1)
            done, _pending = await asyncio.wait({task}, timeout=0.2)
            returned_before_release, closed_before_release = bool(done), buffer.closed
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(finished.wait(), 1)
        await asyncio.wait_for(cleaned.wait(), 1)
        assert returned_before_release, "caller cancellation did not return within the cleanup window"
        assert not closed_before_release, "cleanup closed the resource while finalization was still active"
        assert errors == []
        assert adapter.cleanup_calls == 1

    asyncio.run(scenario())
