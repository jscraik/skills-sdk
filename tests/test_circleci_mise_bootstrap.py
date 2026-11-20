"""Exercise the CircleCI archive-selection step without network or real tools."""

import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = "scripts/circleci-mise-bootstrap.sh"
ARCHIVE = "/tmp/mise.tar.gz"
PINNED_BYTES = b"synthetic pinned archive bytes"


def _supply_checksum_tool(work: Path) -> None:
    """Use the real Linux utility when available, or model its stdin format."""
    if shutil.which("sha256sum") is not None:
        return
    checksum = work / "sha256sum"
    checksum.write_text(
        f"#!{sys.executable}\n"
        "from hashlib import sha256\n"
        "from pathlib import Path\n"
        "import sys\n"
        "expected, path = sys.stdin.readline().rstrip('\\n').split('  ', 1)\n"
        "sys.exit(sha256(Path(path).read_bytes()).hexdigest() != expected)\n",
        encoding="utf-8",
    )
    checksum.chmod(0o755)


class TestCircleCIMiseBootstrap(unittest.TestCase):
    """Exercise selection and verification in a disposable shell environment."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        work = Path(directory.name)
        self.archive = work / "restored.tar.gz"
        self.download = work / "download"
        self.log = work / "fetch.log"
        self.download.write_bytes(PINNED_BYTES)
        curl = work / "curl"
        curl.write_text(
            '#!/bin/bash\nprintf "fetch\\n" >> "$FETCH_LOG"\ncp -- "$FETCH_ARCHIVE" "${@: -1}"\n',
            encoding="utf-8",
        )
        curl.chmod(0o755)
        _supply_checksum_tool(work)
        self.environment = {
            **os.environ,
            "PATH": f"{work}{os.pathsep}{os.environ['PATH']}",
            "FETCH_LOG": str(self.log),
            "FETCH_ARCHIVE": str(self.download),
        }
        source = (ROOT / BOOTSTRAP).read_text(encoding="utf-8")
        source = re.sub(
            r"^readonly mise_sha256=[a-f0-9]{64}$",
            f"readonly mise_sha256={hashlib.sha256(PINNED_BYTES).hexdigest()}",
            source,
            flags=re.MULTILINE,
        )
        source = source.replace(f"={ARCHIVE}", f"={shlex.quote(str(self.archive))}")
        source = source.replace("/tmp/sdk-mise.XXXXXXXX", shlex.quote(str(work / "stage.XXXXXXXX")))
        self.script = work / "bootstrap.sh"
        self.script.write_text(source, encoding="utf-8")

    def _run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.script)], env=self.environment, capture_output=True, text=True, check=False
        )

    def test_cold_miss_downloads_verified_bytes(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.archive.read_bytes(), PINNED_BYTES)
        self.assertEqual(self.log.read_text(encoding="utf-8"), "fetch\n")

    def test_warm_hit_checks_bytes_without_downloading(self) -> None:
        self.archive.write_bytes(PINNED_BYTES)
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SHA-256 verified", result.stdout)
        self.assertFalse(self.log.exists())

    def test_corrupt_cache_uses_verified_download(self) -> None:
        self.archive.write_bytes(b"damaged cached data")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.archive.read_bytes(), PINNED_BYTES)
        self.assertEqual(self.log.read_text(encoding="utf-8"), "fetch\n")

    def test_bad_download_stops_without_promoting_archive(self) -> None:
        self.download.write_bytes(b"damaged downloaded data")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed SHA-256 verification", result.stderr)
        self.assertFalse(self.archive.exists())

    def test_directory_is_not_an_archive_destination(self) -> None:
        self.archive.mkdir()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("archive path is a directory", result.stderr)
        self.assertEqual(list(self.archive.iterdir()), [])


def test_key_changes_with_pin_and_has_no_fallback() -> None:
    """Bind one shared cache key to the pin and keep the existing install proof."""
    cfg = yaml.safe_load((ROOT / ".circleci/config.yml").read_text(encoding="utf-8"))
    jobs = cfg["jobs"]
    key = next(step["restore_cache"]["key"] for step in jobs["prepare"]["steps"] if "restore_cache" in step)
    digest_expr = '{{ checksum "scripts/circleci-mise-bootstrap.sh" }}'
    assert digest_expr in key
    bootstrap = (ROOT / BOOTSTRAP).read_bytes()
    pin = re.search(rb"^readonly mise_sha256=([a-f0-9]{64})$", bootstrap, re.MULTILINE)
    assert pin is not None
    changed = bootstrap.replace(pin[1], b"0" * 64)
    assert key.replace(digest_expr, hashlib.sha256(bootstrap).hexdigest()) != key.replace(
        digest_expr, hashlib.sha256(changed).hexdigest()
    )
    for job in jobs.values():
        steps = job["steps"]
        checks = [step["restore_cache"] for step in steps if "restore_cache" in step]
        assert checks == [{"key": key}]
        install = next(
            step["run"]
            for step in steps
            if isinstance(step, dict) and step.get("run", {}).get("name") == "Install pinned repository tools"
        )
        assert f'{pin[1].decode()}  {ARCHIVE}" | sha256sum -c -' in install["command"]
    saves = [step["when"] for step in jobs["prepare"]["steps"] if "when" in step]
    assert saves == [
        {
            "condition": {"equal": ["main", "<< pipeline.git.branch >>"]},
            "steps": [{"save_cache": {"key": key, "paths": [ARCHIVE]}}],
        }
    ]
    assert not any("save_cache" in str(jobs[name]["steps"]) for name in ("tests", "installed", "validate"))
