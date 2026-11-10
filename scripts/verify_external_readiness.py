"""Run a caller-authorised synthetic readiness-parser probe in the SDK environment.

The supplied digests bind bytes; they do not establish trust or containment.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

_MAX_INPUT_BYTES = 2_000_000
_PROBE_TIMEOUT_SECONDS = 30
_DEPENDENCIES = {"PyYAML": "6.0.3", "pydantic": "2.13.4", "markdown-it-py": "4.2.0", "mdurl": "0.1.2"}
_IMPORTS = ("yaml", "pydantic", "markdown_it", "mdurl")


class InputError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _result(status: str, code: str, returncode: int | None = None, *, attempted: bool = False) -> dict[str, object]:
    return {
        "status": status,
        "code": code,
        "probe_returncode": returncode,
        "probe_attempted": attempted,
        "verified_probe_sha256": None,
        "verified_helper_sha256": None,
        "readiness_clearance": False,
        "security_sandbox": False,
    }


def _check_environment() -> None:
    if sys.version_info[:2] != (3, 12) or not sys.flags.isolated or not hasattr(os, "O_NOFOLLOW"):
        raise InputError("missing_prerequisite")
    _check_dependencies()


def _check_dependencies() -> None:
    try:
        installed = {name: importlib.metadata.version(name) for name in _DEPENDENCIES}
    except importlib.metadata.PackageNotFoundError as exc:
        raise InputError("missing_prerequisite") from exc
    if installed != _DEPENDENCIES:
        raise InputError("missing_prerequisite")
    try:
        for module in _IMPORTS:
            importlib.import_module(module)
    except ImportError as exc:
        raise InputError("missing_prerequisite") from exc


def _read_verified(path: Path, expected: str) -> bytes:
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise InputError("invalid_input")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_INPUT_BYTES:
                raise InputError("invalid_input")
            data = file.read(_MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise InputError("invalid_input") from exc
    if len(data) > _MAX_INPUT_BYTES:
        raise InputError("invalid_input")
    if hashlib.sha256(data).hexdigest() != expected:
        raise InputError("input_digest_mismatch")
    return data


def _run_probe(probe: bytes, helper: bytes) -> dict[str, object]:
    attempted = False
    try:
        with tempfile.TemporaryDirectory(prefix="sdk-readiness-probe-") as directory:
            root = Path(directory)
            probe_path, helper_path = root / "probe.py", root / "helper.py"
            probe_path.write_bytes(probe)
            helper_path.write_bytes(helper)
            env = {"HOME": directory, "TMPDIR": directory, "PATH": ""}
            attempted = True
            try:
                result = subprocess.run(
                    [sys.executable, "-I", "-B", str(probe_path), str(helper_path)],
                    cwd=root,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=_PROBE_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return _result("fail", "timeout", attempted=True)
            except OSError:
                return _result("blocked", "probe_start_failed", attempted=True)
    except OSError:
        return _result("blocked", "probe_storage_failed", attempted=attempted)
    if result.returncode:
        return _result("fail", "test_failure", result.returncode, attempted=True)
    return _result("pass", "probe_completed", result.returncode, attempted=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--probe-sha256", required=True)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--helper-sha256", required=True)
    args = parser.parse_args()
    try:
        _check_environment()
        probe = _read_verified(args.probe, args.probe_sha256)
        helper = _read_verified(args.helper, args.helper_sha256)
        result = _run_probe(probe, helper)
        result["verified_probe_sha256"] = args.probe_sha256
        result["verified_helper_sha256"] = args.helper_sha256
    except InputError as exc:
        result = _result("blocked", exc.code)
    print(json.dumps(result, sort_keys=True))
    return {"pass": 0, "fail": 1, "blocked": 2}[str(result["status"])]


if __name__ == "__main__":
    raise SystemExit(main())
