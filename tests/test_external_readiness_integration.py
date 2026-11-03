from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch, raises

from scripts import verify_external_readiness

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_external_readiness.py"


def test_default_developer_environment_keeps_parser_dependency() -> None:
    project = tomllib.loads((SCRIPT.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    groups = project["dependency-groups"]
    assert "markdown-it-py==4.2.0" in groups["dev"]
    assert groups["readiness-integration"] == ["markdown-it-py==4.2.0"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    probe: Path, helper: Path, *, probe_hash: str | None = None, helper_hash: str | None = None
) -> tuple[int, dict[str, object]]:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(SCRIPT),
            "--probe",
            str(probe),
            "--probe-sha256",
            probe_hash or _sha(probe),
            "--helper",
            str(helper),
            "--helper-sha256",
            helper_hash or _sha(helper),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    return result.returncode, json.loads(result.stdout)


def test_admitted_synthetic_probe_runs_against_snapshot(tmp_path: Path) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("VALUE = 17\n", encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('fixture', sys.argv[1])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "assert module.VALUE == 17\n",
        encoding="utf-8",
    )
    before = (_sha(probe), _sha(helper))
    code, result = _run(probe, helper)
    assert code == 0
    assert result["status"] == "pass"
    assert result["probe_returncode"] == 0
    assert result["probe_attempted"] is True
    assert result["verified_probe_sha256"] == before[0]
    assert result["verified_helper_sha256"] == before[1]
    assert result["readiness_clearance"] is False
    assert result["security_sandbox"] is False
    assert (_sha(probe), _sha(helper)) == before


def test_wrong_helper_digest_blocks_before_probe_runs(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    helper = tmp_path / "helper.py"
    helper.write_text("VALUE = 17\n", encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
    code, result = _run(probe, helper, helper_hash="0" * 64)
    assert code == 2
    assert result["status"] == "blocked"
    assert result["code"] == "input_digest_mismatch"
    assert result["probe_attempted"] is False
    assert result["verified_helper_sha256"] is None
    assert not marker.exists()


def test_wrong_probe_digest_blocks_before_probe_runs(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    helper = tmp_path / "helper.py"
    helper.write_text("VALUE = 17\n", encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
    code, result = _run(probe, helper, probe_hash="0" * 64)
    assert code == 2
    assert result["code"] == "input_digest_mismatch"
    assert not marker.exists()


def test_symlinked_helper_is_rejected(tmp_path: Path) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("VALUE = 17\n", encoding="utf-8")
    link = tmp_path / "helper-link.py"
    link.symlink_to(helper)
    probe = tmp_path / "probe.py"
    probe.write_text("pass\n", encoding="utf-8")
    code, result = _run(probe, link)
    assert code == 2
    assert result["code"] == "invalid_input"


def test_non_regular_input_is_rejected_without_waiting(tmp_path: Path) -> None:
    helper = tmp_path / "helper.fifo"
    os.mkfifo(helper)
    probe = tmp_path / "probe.py"
    probe.write_text("pass\n", encoding="utf-8")
    code, result = _run(probe, helper, helper_hash="0" * 64)
    assert code == 2
    assert result["code"] == "invalid_input"


def test_non_isolated_invocation_is_blocked(tmp_path: Path) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("VALUE = 17\n", encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text("pass\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--probe",
            str(probe),
            "--probe-sha256",
            _sha(probe),
            "--helper",
            str(helper),
            "--helper-sha256",
            _sha(helper),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["code"] == "missing_prerequisite"


def test_missing_parser_import_is_a_missing_prerequisite(monkeypatch: MonkeyPatch) -> None:
    real_import = importlib.import_module

    def missing_mdurl(name: str) -> ModuleType:
        if name == "mdurl":
            raise ModuleNotFoundError(name)
        return real_import(name)

    monkeypatch.setattr(verify_external_readiness.importlib, "import_module", missing_mdurl)
    with raises(verify_external_readiness.InputError, match="missing_prerequisite"):
        verify_external_readiness._check_dependencies()


def test_wrong_dependency_version_blocks_before_import(monkeypatch: MonkeyPatch) -> None:
    actual_version = importlib.metadata.version
    imported: list[str] = []

    def wrong_version(name: str) -> str:
        return "0.0.0" if name == "mdurl" else actual_version(name)

    def record_import(name: str) -> ModuleType:
        imported.append(name)
        raise AssertionError("a mismatched environment must not be imported")

    monkeypatch.setattr(verify_external_readiness.importlib.metadata, "version", wrong_version)
    monkeypatch.setattr(verify_external_readiness.importlib, "import_module", record_import)
    with raises(verify_external_readiness.InputError, match="missing_prerequisite"):
        verify_external_readiness._check_dependencies()
    assert imported == []


def test_failed_probe_is_not_reported_as_pass(tmp_path: Path) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("VALUE = 17\n", encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text("raise SystemExit(7)\n", encoding="utf-8")
    code, result = _run(probe, helper)
    assert code == 1
    assert result["status"] == "fail"
    assert result["code"] == "test_failure"
    assert result["probe_returncode"] == 7


def test_timed_out_probe_is_not_reported_as_pass(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(verify_external_readiness, "_PROBE_TIMEOUT_SECONDS", 0.1)
    result = verify_external_readiness._run_probe(b"import time; time.sleep(5)\n", b"pass\n")
    assert result["status"] == "fail"
    assert result["code"] == "timeout"
    assert result["probe_attempted"] is True


def test_preparation_error_blocks_before_probe(monkeypatch: MonkeyPatch) -> None:
    def unavailable_directory(**kwargs: object) -> None:
        raise OSError("directory unavailable")

    monkeypatch.setattr(verify_external_readiness.tempfile, "TemporaryDirectory", unavailable_directory)
    result = verify_external_readiness._run_probe(b"pass\n", b"pass\n")
    assert result["status"] == "blocked"
    assert result["code"] == "probe_storage_failed"
    assert result["probe_attempted"] is False


def test_cleanup_error_does_not_report_a_successful_probe(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class CleanupFails:
        def __enter__(self) -> str:
            return str(tmp_path)

        def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
            raise OSError("cleanup failed")

    monkeypatch.setattr(verify_external_readiness.tempfile, "TemporaryDirectory", lambda **kwargs: CleanupFails())
    result = verify_external_readiness._run_probe(b"pass\n", b"pass\n")
    assert result["status"] == "blocked"
    assert result["code"] == "probe_storage_failed"
    assert result["probe_attempted"] is True
