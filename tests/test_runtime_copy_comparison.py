from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.cli.main import main
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models import RuntimeCopyComparison

REVISION = "a" * 40


def _package(parent: Path, description: str = "Inspect a bounded example.") -> Path:
    """Create a minimal valid package beneath the selected parent."""
    root = parent / "example"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(f"---\nname: example\ndescription: {description}\n---\n\n# Example\n")
    return root


def test_real_cli_matches_identical_copies_without_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify identical copies pass without changing the runtime entrypoint."""
    source = _package(tmp_path / "source")
    runtime = _package(tmp_path / "runtime")
    before = (runtime / "SKILL.md").stat()
    assert main(["compare-copy", str(source), str(runtime), "--source-revision", REVISION]) == 0
    assert "compare-copy: pass" in capsys.readouterr().out
    after = (runtime / "SKILL.md").stat()
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_compare_copy_json_is_typed_and_versioned(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _package(tmp_path / "source")
    runtime = _package(tmp_path / "runtime")
    assert main(["compare-copy", str(source), str(runtime), "--source-revision", REVISION, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "runtime-copy-comparison/v1"
    assert payload["status"] == "pass"
    assert payload["different_paths"] == []
    SchemaRegistry().validate("runtime-copy-comparison.v1", payload)
    payload["different_paths"] = ["SKILL.md"]
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("runtime-copy-comparison.v1", payload)


@pytest.mark.parametrize("paths", [("../other",), ("/absolute",), ("guide.md", "guide.md"), ("z.md", "a.md")])
def test_comparison_paths_are_portable_sorted_and_unique(tmp_path: Path, paths: tuple[str, ...]) -> None:
    source = _package(tmp_path / "source")
    runtime = _package(tmp_path / "runtime")
    from skills_sdk.validation import validate_skill_package

    source_result = validate_skill_package(source, source_revision=REVISION)
    runtime_result = validate_skill_package(runtime, source_revision=REVISION)
    with pytest.raises((ValidationError, ValueError)):
        RuntimeCopyComparison(status="drift", source=source_result, runtime=runtime_result, different_paths=paths)


def test_recursive_metadata_becomes_comparison_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from skills_sdk.validation import runtime_copy

    source = _package(tmp_path / "source")
    runtime = _package(tmp_path / "runtime")
    monkeypatch.setattr(
        runtime_copy, "validate_skill_package", lambda *_args, **_kwargs: (_ for _ in ()).throw(RecursionError())
    )
    assert main(["compare-copy", str(source), str(runtime), "--source-revision", REVISION, "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


@pytest.mark.parametrize("change", ["content", "extra", "missing"])
def test_real_cli_detects_all_file_differences(tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str) -> None:
    """Verify changed, extra, and missing files all produce drift."""
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
    """Verify invalid metadata, paths, and revisions produce a blocker."""
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
