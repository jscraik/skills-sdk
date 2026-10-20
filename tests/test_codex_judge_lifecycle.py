"""Controlled-process lifecycle and cancellation regression proof."""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from test_codex_judge import _executable

from skills_sdk.core.errors import ContractError
from skills_sdk.providers.codex_judge import CodexJudgeAdapter, CodexJudgeSettings, _run


@pytest.mark.parametrize("mode", ["caller", "cleanup", "cancelled_cleanup_waiter", "cleanup_failure"])
def test_external_cancellation_reaps_process_and_cleans_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Caller cancellation remains cancellation after owned process cleanup."""
    executable = _executable(
        tmp_path,
        "from pathlib import Path; import os; "
        "Path(sys.argv[0]).with_suffix('.pid').write_text(str(os.getpid())); time.sleep(30)",
    )
    marker = executable.with_suffix(".pid")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")

    async def cancel_running() -> None:
        from skills_sdk.providers import codex_judge

        drained = asyncio.Event()
        release = asyncio.Event()
        original = codex_judge._discard_to_eof

        async def controlled_drain(stream: asyncio.StreamReader) -> None:
            await original(stream)
            if not marker.exists():
                return
            drained.set()
            if mode == "cancelled_cleanup_waiter":
                await release.wait()
            if mode == "cleanup_failure":
                raise OSError("private post-drain failure")

        monkeypatch.setattr(codex_judge, "_discard_to_eof", controlled_drain)
        task = asyncio.create_task(adapter.assess("Task", "Response", (("scope", "Scope"),)))
        try:
            for _ in range(500):
                if marker.exists():
                    break
                await asyncio.sleep(0.01)
            assert marker.exists(), "fixture did not start"
            if mode == "cancelled_cleanup_waiter":
                waiter = asyncio.create_task(adapter.cleanup())
                await asyncio.wait_for(drained.wait(), 2)
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
                assert not task.done()
                release.set()
            elif mode == "cleanup_failure":
                with pytest.raises(ContractError) as raised:
                    await adapter.cleanup()
                assert raised.value.code == "codex_judge_cleanup_failed"
            elif mode == "cleanup":
                await adapter.cleanup()
                assert task.done()
            else:
                task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(cancel_running())
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
    assert not list(tmp_path.glob("sdk-judge-*"))


@pytest.mark.parametrize("failure", ["failed", "timeout"])
def test_cancellation_survives_cleanup_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    """A failed drain must annotate, rather than replace, caller cancellation."""
    from skills_sdk.providers import codex_judge

    original = codex_judge._discard_to_eof

    async def failed_drain(stream: asyncio.StreamReader) -> None:
        await original(stream)
        raise OSError("private drain failure")

    monkeypatch.setattr(codex_judge, "_discard_to_eof", failed_drain)
    if failure == "timeout":

        async def expired(awaitable: object, timeout: float) -> object:
            await awaitable
            raise TimeoutError

        monkeypatch.setattr(asyncio, "wait_for", expired)

    async def exercise() -> None:
        task = asyncio.create_task(_run((sys.executable, "-c", "import time; time.sleep(30)"), tmp_path, b"", 5))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as raised:
            await task
        assert "codex_judge_cleanup_" + failure in raised.value.__notes__

    asyncio.run(exercise())


@pytest.mark.parametrize("later_note", [None, "codex_judge_cleanup_failed"])
def test_cleanup_preserves_first_failure_across_cancellations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, later_note: str | None
) -> None:
    """Later cancellation must not erase or replace an unrecovered teardown failure."""
    executable = _executable(tmp_path, "raise AssertionError('not reached')")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    notes = iter(("codex_judge_cleanup_timeout", later_note))

    async def cancelled(*args: object) -> object:
        error = asyncio.CancelledError()
        note = next(notes)
        if note is not None:
            error.add_note(note)
        raise error

    monkeypatch.setattr(adapter, "_assess", cancelled)

    async def exercise() -> None:
        for _ in range(2):
            with pytest.raises(asyncio.CancelledError):
                await adapter.assess("Task", "Response", (("scope", "Scope"),))
        with pytest.raises(ContractError) as raised:
            await adapter.cleanup()
        assert raised.value.code == "codex_judge_cleanup_timeout"

    asyncio.run(exercise())


def test_cleanup_awaits_active_operation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful adapter cleanup must wait for owned assessment teardown."""
    executable = _executable(tmp_path, "raise AssertionError('not reached')")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")

    async def exercise() -> None:
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def pending(*args: object) -> object:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.01)
                stopped.set()

        monkeypatch.setattr(adapter, "_assess", pending)
        task = asyncio.create_task(adapter.assess("Task", "Response", (("scope", "Scope"),)))
        try:
            await started.wait()
            await adapter.cleanup()
            assert stopped.is_set() and task.done()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())
