from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REVISION = "1" * 40


def _skill(root: Path, *, name: str) -> Path:
    root.mkdir()
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: CLI fixture.\n---\n\n# Fixture\n",
        encoding="utf-8",
    )
    return root


def _run(command: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "skills_sdk.cli.main",
            command,
            str(root),
            "--source-revision",
            REVISION,
            "--json",
            "--robot",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_validate_and_build_commands_return_structured_success(tmp_path: Path) -> None:
    root = _skill(tmp_path / "fixture-skill", name="fixture-skill")

    validation = _run("validate", root)
    build = _run("build", root)

    assert validation.returncode == 0, validation.stderr
    assert json.loads(validation.stdout)["status"] == "pass"
    assert build.returncode == 0, build.stderr
    assert json.loads(build.stdout)["status"] == "built"


def test_validate_and_build_commands_return_typed_blocker_exit(tmp_path: Path) -> None:
    root = _skill(tmp_path / "fixture-skill", name="wrong-name")

    validation = _run("validate", root)
    build = _run("build", root)

    assert validation.returncode == 2
    assert json.loads(validation.stdout)["findings"][0]["code"] == "name_mismatch"
    assert build.returncode == 2
    assert json.loads(build.stdout)["blocker"]["code"] == "name_mismatch"


def test_invalid_source_revision_returns_structured_blocker(tmp_path: Path) -> None:
    root = _skill(tmp_path / "fixture-skill", name="fixture-skill")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "skills_sdk.cli.main",
            "validate",
            str(root),
            "--source-revision",
            "BAD",
            "--json",
            "--robot",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["findings"][0]["code"] == "invalid_source_revision"
