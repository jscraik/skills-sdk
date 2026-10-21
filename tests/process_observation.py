"""Test-only termination observations; never signal a saved process identity."""

import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessObservation:
    """Retain a kernel birth identity where the platform exposes one."""

    state: str
    birth: str | None


def read_linux_process(pid: int, proc: Path = Path("/proc")) -> ProcessObservation | None:
    """Read state and start ticks, failing closed on malformed or unreadable data."""
    if pid <= 0:
        raise ValueError("observation requires a positive process id")
    try:
        record = (proc / str(pid) / "stat").read_text()
    except FileNotFoundError:
        if not proc.is_dir():
            raise OSError("process identity source unavailable") from None
        return None
    prefix, separator, tail = record.rpartition(")")
    fields = tail.split()
    if not separator or prefix.split(" ", 1)[0] != str(pid) or len(fields) < 20:
        raise ValueError("invalid process identity record")
    state, birth = fields[0], fields[19]
    if state not in {"R", "S", "D", "Z", "T", "t", "X", "x", "K", "W", "P", "I"} or not (
        birth.isascii() and birth.isdecimal()
    ):
        raise ValueError("invalid process state or birth identity")
    return ProcessObservation(state, birth)


def read_process(pid: int) -> ProcessObservation | None:
    """On non-Linux hosts require disappearance rather than infer PID reuse."""
    if pid <= 0:
        raise ValueError("observation requires a positive process id")
    if sys.platform == "linux":
        return read_linux_process(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    return ProcessObservation("present", None)


def assert_process_terminated(
    pid: int,
    original: ProcessObservation,
    *,
    timeout: float = 2,
    observe: Callable[[int], ProcessObservation | None] = read_process,
) -> None:
    """Reject a live original; a zombie proves termination, not orphan reaping."""
    deadline = time.monotonic() + timeout
    while True:
        current = observe(pid)
        if current is None:
            return
        if original.birth is not None and current.birth is not None and current.birth != original.birth:
            return
        if current.state == "Z" and original.birth is not None and current.birth == original.birth:
            return
        assert time.monotonic() < deadline, f"original process survived cleanup: {original!r}; observed {current!r}"
        time.sleep(0.01)
