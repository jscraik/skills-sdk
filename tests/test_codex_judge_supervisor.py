"""Owned-anchor lifecycle proof without parent numeric process signalling."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.providers import _codex_judge_channel as channel
from skills_sdk.providers.codex_judge import _run


def _forbid_parent_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object) -> None:
        pytest.fail("parent must never signal a cached process-group identity")

    monkeypatch.setattr(os, "killpg", forbidden)


@pytest.mark.parametrize("script", ["print('complete')", "raise SystemExit(7)"])
def test_normal_exit_never_signals_a_saved_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    _forbid_parent_signal(monkeypatch)
    if "SystemExit" in script:
        with pytest.raises(ContractError) as raised:
            asyncio.run(_run((sys.executable, "-c", script), tmp_path, b"", 3))
        assert raised.value.code == "codex_judge_process_failed"
    else:
        assert asyncio.run(_run((sys.executable, "-c", script), tmp_path, b"", 3)) == b"complete\n"


def test_supervisor_descriptors_do_not_reach_target(tmp_path: Path) -> None:
    script = (
        "import os; fds=[]\n"
        "for fd in range(3,64):\n"
        " try: os.fstat(fd);fds.append(fd)\n"
        " except OSError: pass\n"
        "print(fds)"
    )
    assert asyncio.run(_run((sys.executable, "-c", script), tmp_path, b"", 3)) == b"[]\n"


@pytest.mark.parametrize("after_status", [False, True])
def test_unexpected_supervisor_death_blocks_cleanup_without_numeric_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_status: bool
) -> None:
    helper = tmp_path / "dead-supervisor.py"
    helper.write_text(
        "import os,sys\n"
        + ("os.write(int(sys.argv[2]), b'sdk-judge-supervisor/v1 exit 0\\n')\n" if after_status else "")
        + "os._exit(0)\n"
    )
    monkeypatch.setattr(channel, "_HELPER_PATH", helper)
    _forbid_parent_signal(monkeypatch)
    with pytest.raises(ContractError) as raised:
        asyncio.run(_run((sys.executable, "-c", "pass"), tmp_path, b"", 3))
    assert raised.value.code == ("codex_judge_cleanup_failed" if after_status else "codex_judge_protocol_invalid")


@pytest.mark.parametrize("raw", [b"wrong\n", b"sdk-judge-supervisor/v1 exit nope\n", b"x" * 200 + b"\n"])
def test_malformed_supervisor_status_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes) -> None:
    helper = tmp_path / "invalid-supervisor.py"
    helper.write_text(
        "import os,sys,signal\n"
        f"os.write(int(sys.argv[2]), {raw!r})\n"
        "os.read(int(sys.argv[1]),1)\n"
        "os.write(int(sys.argv[2]), b'sdk-judge-supervisor/v1 stopping\\n')\n"
        "os.killpg(os.getpgrp(),signal.SIGKILL)\n"
    )
    monkeypatch.setattr(channel, "_HELPER_PATH", helper)
    _forbid_parent_signal(monkeypatch)
    with pytest.raises(ContractError) as raised:
        asyncio.run(_run((sys.executable, "-c", "pass"), tmp_path, b"", 3))
    assert raised.value.code == "codex_judge_protocol_invalid"


def test_missing_target_is_a_typed_start_failure(tmp_path: Path) -> None:
    with pytest.raises(ContractError) as raised:
        asyncio.run(_run((str(tmp_path / "missing-target"),), tmp_path, b"", 3))
    assert raised.value.code == "codex_judge_start_failed"


def test_partial_descriptor_allocation_is_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = os.pipe
    allocated: list[int] = []

    def fail_second_pipe() -> tuple[int, int]:
        if allocated:
            raise OSError("controlled pipe allocation failure")
        pair = original()
        allocated.extend(pair)
        return pair

    monkeypatch.setattr(os, "pipe", fail_second_pipe)
    with pytest.raises(ContractError) as raised:
        asyncio.run(_run((sys.executable, "-c", "pass"), tmp_path, b"", 3))
    assert raised.value.code == "codex_judge_start_failed"
    for descriptor in allocated:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("tail", [b"exit 0\n", b"stopping\nextra\n", b"stopp"])
def test_duplicate_trailing_or_truncated_status_cannot_clear(tail: bytes) -> None:
    async def invoke() -> None:
        supervisor = channel.JudgeSupervisor()
        supervisor.reader.feed_data(b"sdk-judge-supervisor/v1 exit 0\n" + b"sdk-judge-supervisor/v1 " + tail)
        supervisor.reader.feed_eof()
        assert await supervisor.exit_code() == 0
        with pytest.raises(ContractError):
            await supervisor.verify_stop()

    asyncio.run(invoke())


def test_stop_during_spawn_is_serialized_with_group_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = tmp_path / "slow-supervisor.py"
    entered = tmp_path / "spawn-entered"
    target_pid = tmp_path / "target.pid"
    escaped = tmp_path / "target-completed"
    helper.write_text(
        "import runpy,sys,time,pathlib\n"
        f"namespace=runpy.run_path({str(channel._HELPER_PATH)!r})\n"
        "original=namespace['subprocess'].Popen\n"
        "def delayed(*args,**kwargs):\n"
        f" pathlib.Path({str(entered)!r}).write_text('entered')\n"
        " time.sleep(0.2)\n"
        " child=original(*args,**kwargs)\n"
        f" pathlib.Path({str(target_pid)!r}).write_text(str(child.pid))\n"
        " return child\n"
        "namespace['subprocess'].Popen=delayed\n"
        "namespace['supervise'](int(sys.argv[1]),int(sys.argv[2]),sys.argv[3:])\n"
    )
    monkeypatch.setattr(channel, "_HELPER_PATH", helper)
    _forbid_parent_signal(monkeypatch)

    async def invoke() -> None:
        supervisor = channel.JudgeSupervisor()
        script = f"import time,pathlib;time.sleep(0.5);pathlib.Path({str(escaped)!r}).write_text('escaped')"
        process = await supervisor.launch((sys.executable, "-c", script), tmp_path)
        try:
            async with asyncio.timeout(3):
                while not entered.exists():
                    await asyncio.sleep(0.01)
                supervisor.stop()
                assert await process.wait() == -9
                await supervisor.verify_stop()
            assert target_pid.exists()
            await asyncio.sleep(0.6)
            assert not escaped.exists(), "target escaped the serialized group stop"
        finally:
            supervisor.stop()
            supervisor.close()

    asyncio.run(invoke())


def test_native_supervisor_denied_termination_is_a_cleanup_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = tmp_path / "denied-supervisor.py"
    helper.write_text(
        "import runpy,sys\n"
        f"namespace=runpy.run_path({str(channel._HELPER_PATH)!r})\n"
        "def denied(*args): raise PermissionError('controlled denial')\n"
        "namespace['os'].killpg=denied\n"
        "namespace['supervise'](int(sys.argv[1]),int(sys.argv[2]),sys.argv[3:])\n"
    )
    monkeypatch.setattr(channel, "_HELPER_PATH", helper)
    _forbid_parent_signal(monkeypatch)
    with pytest.raises(ContractError) as raised:
        asyncio.run(_run((sys.executable, "-c", "print('complete')"), tmp_path, b"", 3))
    assert raised.value.code == "codex_judge_cleanup_failed"


def test_stop_frame_cannot_be_followed_by_racing_target_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = tmp_path / "delayed-stop-supervisor.py"
    stopping = tmp_path / "stopping"
    helper.write_text(
        "import runpy,sys,time,pathlib\n"
        f"namespace=runpy.run_path({str(channel._HELPER_PATH)!r})\n"
        "original=namespace['os'].killpg\n"
        "def delayed(*args):\n"
        f" pathlib.Path({str(stopping)!r}).write_text('stopping')\n"
        " time.sleep(0.3);original(*args)\n"
        "namespace['os'].killpg=delayed\n"
        "namespace['supervise'](int(sys.argv[1]),int(sys.argv[2]),sys.argv[3:])\n"
    )
    monkeypatch.setattr(channel, "_HELPER_PATH", helper)
    target = f"import pathlib,time\nwhile not pathlib.Path({str(stopping)!r}).exists(): time.sleep(0.001)"
    with pytest.raises(ContractError) as raised:
        asyncio.run(_run((sys.executable, "-c", target), tmp_path, b"", 0.15))
    assert raised.value.code == "codex_judge_timeout"
    assert raised.value.details == ()
