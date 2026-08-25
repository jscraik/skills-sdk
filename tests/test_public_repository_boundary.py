from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BANNED_PATH_PARTS = {".agents", ".codex", ".harness", "packages"}
BANNED_TEXT = (
    "/" + "Users" + "/",
    "BEGIN " + "OPENSSH PRIVATE KEY",
    "BEGIN " + "PRIVATE KEY",
    "tessl" + "_api_key",
)


def _source_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [REPO_ROOT / value for value in result.stdout.splitlines() if value]


def test_seed_has_no_private_package_or_runtime_roots() -> None:
    offending = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _source_files()
        if BANNED_PATH_PARTS.intersection(path.relative_to(REPO_ROOT).parts)
    ]
    assert offending == []


def test_seed_has_no_machine_paths_keys_or_provider_secrets() -> None:
    offending: list[str] = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(marker.casefold() in text.casefold() for marker in BANNED_TEXT):
            offending.append(path.relative_to(REPO_ROOT).as_posix())
    assert offending == []
