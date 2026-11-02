"""Actual supervised timeout and cancellation proof without live model calls."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from process_observation import assert_process_terminated, read_process
from test_fm_advisory import request_data

from skills_sdk.models.advisory import FMAdvisoryRequest
from skills_sdk.providers import fm_advisory


@pytest.mark.parametrize("cancel", [False, True])
def test_advisory_timeout_or_cancel_stops_descendant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cancel: bool,
) -> None:
    marker = tmp_path / "owned-child.pid"
    script = (
        "import subprocess,sys,pathlib,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"pathlib.Path({str(marker)!r}).write_text(str(p.pid)); time.sleep(60)"
    )
    original_run = fm_advisory._run
    calls = []
    roots = []

    async def controlled(argv: tuple[str, ...], cwd: Path, payload: bytes, seconds: float) -> bytes:
        calls.append(argv)
        if argv[1] == "config":
            return b"(none)"
        roots.append(cwd)
        return await original_run((sys.executable, "-c", script), cwd, payload, seconds)

    monkeypatch.setattr(fm_advisory, "_run", controlled)
    monkeypatch.setattr(fm_advisory, "_availability", lambda: None)

    async def invoke() -> None:
        task = asyncio.create_task(
            fm_advisory.advise_with_fm(
                FMAdvisoryRequest.model_validate(request_data()),
                timeout_seconds=1,
            )
        )
        try:
            for _ in range(100):
                if marker.exists():
                    break
                await asyncio.sleep(0.01)
            assert marker.exists(), "controlled child did not start"
            pid = int(marker.read_text())
            observed = read_process(pid)
            assert observed is not None
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                result = await task
                assert result.status == "error" and result.reason == "execution_timeout"
                assert result.generation_attempted and result.judgement is None
            assert_process_terminated(pid, observed)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(invoke())
    assert len(calls) == 2
    assert roots and all(not root.exists() for root in roots)
