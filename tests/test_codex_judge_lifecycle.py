"""Controlled-process lifecycle and cancellation regression proof."""

import asyncio
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path

import pytest
from test_codex_judge import _events, _executable

from skills_sdk.core.errors import ContractError
from skills_sdk.providers.codex_judge import CodexJudgeAdapter, CodexJudgeSettings, _run


@pytest.mark.parametrize("primary", ["success", "process", "cancelled"])
def test_scratch_teardown_failure_preserves_primary_and_cleanup_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary: str
) -> None:
    """Scratch removal failure stays private and cannot erase primary failure."""
    from skills_sdk.providers import codex_judge

    original = codex_judge.tempfile.TemporaryDirectory.cleanup

    def failed_cleanup(workspace: object) -> None:
        original(workspace)
        raise PermissionError(str(tmp_path))

    async def invoke(*args: object) -> bytes:
        if primary == "process":
            raise ContractError("codex_judge_process_failed", "Controlled process failure")
        if primary == "cancelled":
            raise asyncio.CancelledError
        return b"codex-cli 0.153.4" if args[2] == b"" else _events().encode()

    monkeypatch.setattr(codex_judge.tempfile.TemporaryDirectory, "cleanup", failed_cleanup)
    monkeypatch.setattr(codex_judge, "_run", invoke)
    executable = _executable(tmp_path, "raise AssertionError('not reached')")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    expected = asyncio.CancelledError if primary == "cancelled" else ContractError
    with pytest.raises(expected) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert str(tmp_path) not in str(raised.value)
    if isinstance(raised.value, ContractError):
        expected_code = "codex_judge_process_failed" if primary == "process" else "codex_judge_cleanup_failed"
        assert raised.value.code == expected_code
    else:
        assert "codex_judge_cleanup_failed" in raised.value.__notes__
    with pytest.raises(ContractError) as repeated:
        asyncio.run(adapter.cleanup())
    assert repeated.value.code == "codex_judge_cleanup_failed"
    assert not list(tmp_path.glob("sdk-judge-*"))


def test_transport_oserror_is_a_private_process_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Post-start pipe errors remain typed process failures and drain owned work."""
    from skills_sdk.providers import codex_judge

    async def failed_read(stream: asyncio.StreamReader, limit: int) -> bytes:
        raise PermissionError(str(tmp_path))

    monkeypatch.setattr(codex_judge, "_read_bounded", failed_read)
    with pytest.raises(ContractError) as raised:
        asyncio.run(_run((sys.executable, "-c", "import time; time.sleep(30)"), tmp_path, b"", 5))
    assert raised.value.code == "codex_judge_process_failed"
    assert str(tmp_path) not in str(raised.value)
    assert raised.value.__suppress_context__


@pytest.mark.parametrize("later", ["none", "drain", "timeout"])
def test_termination_oserror_is_retained_as_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, later: str
) -> None:
    """A post-start termination error cannot masquerade as scratch unavailability."""
    from skills_sdk.providers import codex_judge

    executable = _executable(tmp_path, "print(" + repr(_events()) + ")")
    original = os.killpg

    def failed_termination(pid: int, sig: int) -> None:
        with suppress(ProcessLookupError):
            original(pid, signal.SIGKILL)
        raise PermissionError(str(tmp_path))

    monkeypatch.setattr(codex_judge.os, "killpg", failed_termination)
    if later == "drain":
        original_drain = codex_judge._discard_to_eof

        async def failed_drain(stream: asyncio.StreamReader) -> None:
            await original_drain(stream)
            raise OSError("private drain failure")

        monkeypatch.setattr(codex_judge, "_discard_to_eof", failed_drain)
    elif later == "timeout":

        async def expired(awaitable: object, timeout: float) -> object:
            await awaitable
            raise TimeoutError

        monkeypatch.setattr(asyncio, "wait_for", expired)
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_cleanup_failed"
    assert raised.value.message == "Judge termination could not complete"
    if later != "none":
        assert len(raised.value.details) == 1
        expected = "codex_judge_cleanup_timeout" if later == "timeout" else "codex_judge_cleanup_failed"
        assert raised.value.details[0].code == expected
    assert str(tmp_path) not in str(raised.value)
    with pytest.raises(ContractError) as repeated:
        asyncio.run(adapter.cleanup())
    assert repeated.value.code == "codex_judge_cleanup_failed"
    assert not list(tmp_path.glob("sdk-judge-*"))


@pytest.mark.parametrize("failure", ["missing_parent", "allocation_denied", "schema_write_denied"])
def test_scratch_setup_failure_is_typed_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Changed scratch availability must fail safely and permit a later retry."""
    from skills_sdk.providers import codex_judge

    executable = _executable(tmp_path, "print(" + repr(_events()) + ")")
    parent = tmp_path / "private-host-workspace"
    parent.mkdir()
    adapter = CodexJudgeAdapter(executable, parent, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    with monkeypatch.context() as patch:
        if failure == "missing_parent":
            parent.rmdir()
        elif failure == "allocation_denied":

            def denied_allocation(*args: object, **kwargs: object) -> str:
                raise PermissionError(str(parent))

            patch.setattr(codex_judge.tempfile, "mkdtemp", denied_allocation)
        else:

            def denied_write(*args: object, **kwargs: object) -> int:
                raise PermissionError(str(parent))

            patch.setattr(Path, "write_text", denied_write)
        with pytest.raises(ContractError) as raised:
            asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_workspace_unavailable"
    assert str(parent) not in str(raised.value)
    assert str(parent) not in repr(raised.value.details)
    assert raised.value.__suppress_context__
    assert adapter.last_observation is None
    assert not list(parent.glob("sdk-judge-*"))
    parent.mkdir(exist_ok=True)
    assert asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),))).score == 0.9


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


@pytest.mark.parametrize("primary", ["success", "process", "timeout"])
@pytest.mark.parametrize("previous", [None, "codex_judge_cleanup_timeout"])
@pytest.mark.parametrize("failure", ["failed", "timeout"])
def test_cleanup_remembers_non_cancelled_teardown_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary: str, previous: str | None, failure: str
) -> None:
    """A later cleanup must retain the first failure from real process teardown."""
    from skills_sdk.providers import codex_judge

    executable = tmp_path / "controlled-codex"
    action = {"success": "print('codex-cli 0.153.4')", "process": "sys.exit(7)", "timeout": "time.sleep(30)"}
    executable.write_text(f"#!{sys.executable}\nimport sys,time\n{action[primary]}\n")
    executable.chmod(0o755)
    adapter = CodexJudgeAdapter(
        executable, tmp_path, CodexJudgeSettings("model", "0.153.4", (), timeout_seconds=1), "Rubric"
    )
    adapter._cleanup_error = previous
    original = codex_judge._discard_to_eof

    async def failed_drain(stream: asyncio.StreamReader) -> None:
        await original(stream)
        raise OSError("private fixture teardown failure")

    monkeypatch.setattr(codex_judge, "_discard_to_eof", failed_drain)
    if failure == "timeout":

        async def expired(awaitable: object, timeout: float) -> object:
            await awaitable
            raise TimeoutError

        monkeypatch.setattr(asyncio, "wait_for", expired)

    async def exercise() -> None:
        with pytest.raises(ContractError) as raised:
            await adapter.assess("Task", "Response", (("scope", "Scope"),))
        expected = {"success": "cleanup_" + failure, "process": "process_failed", "timeout": "timeout"}
        assert raised.value.code == "codex_judge_" + expected[primary]
        if primary != "success":
            assert any(
                isinstance(item, ContractError) and item.code == "codex_judge_cleanup_" + failure
                for item in raised.value.details
            )
        for _ in range(2):
            with pytest.raises(ContractError) as cleanup:
                await adapter.cleanup()
            assert cleanup.value.code == (previous or "codex_judge_cleanup_" + failure)

    asyncio.run(exercise())
    assert not list(tmp_path.glob("sdk-judge-*"))
