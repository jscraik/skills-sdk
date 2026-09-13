from __future__ import annotations

from pathlib import Path

import pytest

from skills_sdk.cli.main import main

REVISION = "a" * 40


def _package(parent: Path, description: str = "Inspect a bounded example.") -> Path:
    root = parent / "example"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(f"---\nname: example\ndescription: {description}\n---\n\n# Example\n")
    return root


def test_real_cli_matches_identical_copies_without_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _package(tmp_path / "source")
    runtime = _package(tmp_path / "runtime")
    before = (runtime / "SKILL.md").stat()
    assert main(["compare-copy", str(source), str(runtime), "--source-revision", REVISION]) == 0
    assert "compare-copy: pass" in capsys.readouterr().out
    after = (runtime / "SKILL.md").stat()
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


@pytest.mark.parametrize("change", ["content", "extra", "missing"])
def test_real_cli_detects_all_file_differences(tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str) -> None:
    source = _package(tmp_path / "source")
    runtime = _package(tmp_path / "runtime")
    (source / "guide.md").write_text("Expected content\n")
    if change == "content":
        (runtime / "guide.md").write_text("Different content\n")
    elif change == "extra":
        (runtime / "guide.md").write_text("Expected content\n")
        (runtime / "extra.md").write_text("Unexpected file\n")
    assert main(["compare-copy", str(source), str(runtime), "--source-revision", REVISION]) == 2
    output = capsys.readouterr().out
    assert "compare-copy: drift" in output
    assert "different:" in output


@pytest.mark.parametrize("invalid", ["metadata", "symlink", "revision"])
def test_real_cli_does_not_call_invalid_sources_a_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], invalid: str
) -> None:
    source = _package(tmp_path / "source")
    runtime = _package(tmp_path / "runtime")
    revision = REVISION
    if invalid == "metadata":
        for root in (source, runtime):
            (root / "SKILL.md").write_text("---\nname: example\nunknown: value\n---\n")
    elif invalid == "symlink":
        (runtime / "guide.md").symlink_to(source / "SKILL.md")
    else:
        revision = "not-a-revision"
    assert main(["compare-copy", str(source), str(runtime), "--source-revision", revision]) == 2
    assert "compare-copy: blocked" in capsys.readouterr().out
