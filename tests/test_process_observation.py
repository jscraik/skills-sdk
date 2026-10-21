"""Prove termination observation cannot accept a live original or unknown state."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from process_observation import ProcessObservation, assert_process_terminated, read_linux_process, read_process


@pytest.mark.parametrize("current", [None, ProcessObservation("Z", "100"), ProcessObservation("S", "101")])
def test_disappeared_zombie_and_reused_pid_are_not_live_originals(current: ProcessObservation | None) -> None:
    assert_process_terminated(123, ProcessObservation("S", "100"), timeout=0, observe=lambda pid: current)


@pytest.mark.parametrize(
    "current", [ProcessObservation("S", "100"), ProcessObservation("present", None), ProcessObservation("Z", None)]
)
def test_live_or_unidentified_original_cannot_clear(current: ProcessObservation) -> None:
    with pytest.raises(AssertionError, match="survived cleanup"):
        assert_process_terminated(123, ProcessObservation("S", "100"), timeout=0, observe=lambda pid: current)


def test_unreadable_identity_does_not_clear() -> None:
    def denied(pid: int) -> ProcessObservation | None:
        raise PermissionError("controlled identity denial")

    with pytest.raises(PermissionError):
        assert_process_terminated(123, ProcessObservation("S", "100"), timeout=0, observe=denied)


@pytest.mark.parametrize(
    "record", ["", "123 (name) S", "124 (name) S " + "0 " * 18 + "100", "123 (name) ? " + "0 " * 18 + "100"]
)
def test_malformed_identity_does_not_clear(tmp_path: Path, record: str) -> None:
    path = tmp_path / "123"
    path.mkdir()
    (path / "stat").write_text(record)
    with pytest.raises(ValueError):
        read_linux_process(123, tmp_path)


def test_linux_identity_handles_parentheses_in_command(tmp_path: Path) -> None:
    path = tmp_path / "123"
    path.mkdir()
    (path / "stat").write_text("123 (worker (name)) Z " + "0 " * 18 + "100")
    assert read_linux_process(123, tmp_path) == ProcessObservation("Z", "100")
    assert read_linux_process(124, tmp_path) is None


def test_missing_identity_source_does_not_clear(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="identity source unavailable"):
        read_linux_process(123, tmp_path / "unavailable")


def test_real_live_child_is_rejected_then_owned_wait_proves_disappearance() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        original = read_process(child.pid)
        assert original is not None
        with pytest.raises(AssertionError, match="survived cleanup"):
            assert_process_terminated(child.pid, original, timeout=0.02)
    finally:
        child.terminate()
        child.wait(timeout=3)
    assert_process_terminated(child.pid, original)


@pytest.mark.skipif(sys.platform != "linux", reason="requires native Linux procfs zombie observation")
def test_native_linux_zombie_is_dead_even_while_pid_probe_succeeds() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        original = read_process(child.pid)
        assert original is not None
        deadline = time.monotonic() + 2
        while True:
            current = read_process(child.pid)
            assert current is not None
            if current.state == "Z":
                break
            assert time.monotonic() < deadline, "owned child did not exit"
            time.sleep(0.01)
        os.kill(child.pid, 0)
        assert_process_terminated(child.pid, original, timeout=0)
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=3)
