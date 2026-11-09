"""Resource-boundary regressions for untrusted standalone package intake."""

import subprocess
import sys
from pathlib import Path

import installed_plugin_intake_smoke
import pytest
from test_package_intake import _context as _intake_context
from test_plugin_normalization import _context as _normalization_context
from test_plugin_normalization import _normalize

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.intake import intake_skill_package
from skills_sdk.packaging import build_skill_package
from skills_sdk.validation import skill_package as capture
from skills_sdk.validation import validate_skill_package


def _package(tmp_path: Path) -> Path:
    root = tmp_path / "bounded-skill"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: bounded-skill\ndescription: Safe fixture.\n---\nDo work.\n")
    return root


def test_incomplete_capture_retains_blocked_intake_contract_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "synthetic-skill"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: synthetic-skill\ndescription: Safe fixture.\n---\nDo work.\n")
    oversized = root / "A.txt"
    oversized.write_bytes(b"x" * 129)
    monkeypatch.setattr(capture, "_MAX_PACKAGE_FILE_BYTES", 128)

    receipt = intake_skill_package(root, _intake_context())
    assert receipt.status == "blocked" and receipt.candidate is not None and receipt.decision is not None
    assert receipt.blocker is not None and receipt.blocker.code == "package_resource_limit"
    assert {finding.code for finding in receipt.validation.findings} == {"package_resource_limit"}
    SchemaRegistry().validate("skill-package-intake.v1", receipt.model_dump(mode="json"))

    oversized.unlink()
    assert intake_skill_package(root, _intake_context()).status == "normalized"


@pytest.mark.parametrize("mutate", [False, True], ids=["unchanged", "same-size-rewrite"])
def test_intake_smoke_detects_same_size_source_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate: bool
) -> None:
    root = tmp_path.resolve()
    source = root / "synthetic-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: synthetic-skill\ndescription: Safe fixture.\n---\nDo work.\n")
    baseline = _normalize(source, root / "baseline-plugin")
    assert baseline.source_intake.candidate is not None
    context_path = root / "context.json"
    context_path.write_text(_normalization_context().model_dump_json())
    command = [
        str(Path(sys.executable).with_name("skills-sdk")),
        "normalize-plugin",
        str(source),
        str(root / "cli-plugin"),
        "--context",
        str(context_path),
        "--plugin-name",
        "fixture-plugin",
        "--plugin-version",
        "1.0.0",
        "--plugin-description",
        "Synthetic fixture.",
        "--json",
        "--robot",
    ]
    original_run = subprocess.run

    def run_with_rewrite(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        completed = original_run(*args, **kwargs)
        if completed.returncode == 2:
            with (source / "oversized.md").open("r+b") as stream:
                stream.write(b"y")
        return completed

    if mutate:
        monkeypatch.setattr(installed_plugin_intake_smoke.subprocess, "run", run_with_rewrite)
        with pytest.raises(AssertionError, match="oversized source bytes changed"):
            installed_plugin_intake_smoke._verify_normalization_capture_limit(
                command, source, root, baseline.source_intake.candidate.model_dump(mode="json")
            )
    else:
        installed_plugin_intake_smoke._verify_normalization_capture_limit(
            command, source, root, baseline.source_intake.candidate.model_dump(mode="json")
        )


@pytest.mark.parametrize(
    "value",
    ["{a: &a one, b: *a}", "{<<: {a: one}}", "[" * 600 + "0" + "]" * 600, "[" + "0," * 20_001 + "]"],
    ids=["alias", "merge", "depth", "nodes"],
)
def test_frontmatter_work_returns_typed_blocker(tmp_path: Path, value: str) -> None:
    root = _package(tmp_path)
    (root / "SKILL.md").write_text(
        "---\nname: bounded-skill\ndescription: Safe fixture.\nmetadata: " + value + "\n---\nDo work.\n"
    )
    result = validate_skill_package(root, source_revision="1" * 40)
    assert result.status == "blocked"
    assert "invalid_frontmatter" in {finding.code for finding in result.findings}


@pytest.mark.parametrize("depth, expected", [(126, "pass"), (127, "blocked")])
def test_frontmatter_composition_depth_boundary(tmp_path: Path, depth: int, expected: str) -> None:
    root = _package(tmp_path)
    value = "[" * depth + "0" + "]" * depth
    (root / "SKILL.md").write_text(
        "---\nname: bounded-skill\ndescription: Safe fixture.\nmetadata: " + value + "\n---\nDo work.\n"
    )
    result = validate_skill_package(root, source_revision="1" * 40)
    assert result.status == expected
    if expected == "blocked":
        assert "invalid_frontmatter" in {finding.code for finding in result.findings}


@pytest.mark.parametrize("limit", ["_MAX_PACKAGE_FILE_BYTES", "_MAX_PACKAGE_TOTAL_BYTES"])
def test_capture_byte_limits_block_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str) -> None:
    root = _package(tmp_path)
    (root / "resource.txt").write_bytes(b"x" * 257)
    monkeypatch.setattr(capture, limit, 256, raising=False)
    result = build_skill_package(root, source_revision="1" * 40)
    assert result.status == "blocked"
    assert result.blocker is not None and result.blocker.code == "package_resource_limit"
    validation = validate_skill_package(root, source_revision="1" * 40)
    assert "package_resource_limit" in {finding.code for finding in validation.findings}


def test_capture_resource_count_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _package(tmp_path)
    for name in ("a.txt", "b.txt", "c.txt"):
        (root / name).write_text("small")
    monkeypatch.setattr(capture, "_MAX_PACKAGE_RESOURCES", 3, raising=False)
    result = validate_skill_package(root, source_revision="1" * 40)
    assert result.status == "blocked"
    assert "package_resource_limit" in {finding.code for finding in result.findings}


def test_normal_package_still_builds(tmp_path: Path) -> None:
    result = build_skill_package(_package(tmp_path), source_revision="1" * 40)
    assert result.status == "built"


def test_growing_file_read_stops_at_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _package(tmp_path)
    resource = root / "resource.txt"
    resource.write_bytes(b"x")
    resource_stat = resource.stat()
    resource_identity = (resource_stat.st_dev, resource_stat.st_ino)
    original_read = capture.os.read
    bytes_returned = 0

    def growing_read(descriptor: int, size: int) -> bytes:
        nonlocal bytes_returned
        observed = capture.os.fstat(descriptor)
        if (observed.st_dev, observed.st_ino) == resource_identity:
            assert size <= 256 - bytes_returned + 1, "capture requested more than the remaining budget plus one"
            payload = b"x" * min(size, 200)
            bytes_returned += len(payload)
            return payload
        return original_read(descriptor, size)

    monkeypatch.setattr(capture, "_MAX_PACKAGE_FILE_BYTES", 256)
    monkeypatch.setattr(capture.os, "read", growing_read)
    result = validate_skill_package(root, source_revision="1" * 40)
    assert result.status == "blocked"
    assert {"package_resource_limit", "source_changed"} & {finding.code for finding in result.findings}
    assert 0 < bytes_returned <= 257


def test_exact_capture_budgets_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _package(tmp_path)
    payload = (root / "SKILL.md").read_bytes()
    monkeypatch.setattr(capture, "_MAX_PACKAGE_FILE_BYTES", len(payload))
    monkeypatch.setattr(capture, "_MAX_PACKAGE_TOTAL_BYTES", len(payload))
    monkeypatch.setattr(capture, "_MAX_PACKAGE_RESOURCES", 1)
    assert validate_skill_package(root, source_revision="1" * 40).status == "pass"


@pytest.mark.parametrize("excess", [0, 1], ids=["exact-total", "one-byte-over-total"])
def test_total_capture_budget_accumulates_across_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, excess: int
) -> None:
    root = _package(tmp_path)
    (root / "a.txt").write_bytes(b"a" * 100)
    (root / "b.txt").write_bytes(b"b" * 100)
    total = (root / "SKILL.md").stat().st_size + 200
    monkeypatch.setattr(capture, "_MAX_PACKAGE_FILE_BYTES", 128)
    monkeypatch.setattr(capture, "_MAX_PACKAGE_TOTAL_BYTES", total - excess)
    validation = validate_skill_package(root, source_revision="1" * 40)
    receipt = build_skill_package(root, source_revision="1" * 40)
    assert validation.status == ("blocked" if excess else "pass")
    assert receipt.status == ("blocked" if excess else "built")
    if excess:
        assert "package_resource_limit" in {finding.code for finding in validation.findings}
        assert receipt.blocker is not None and receipt.blocker.code == "package_resource_limit"
    else:
        assert {item.path for item in validation.files} == {"SKILL.md", "a.txt", "b.txt"}


@pytest.mark.parametrize(
    "failure, code",
    [("changed", "source_changed"), ("unreadable", "unreadable_package_file"), ("limit", "package_resource_limit")],
)
def test_capture_stops_across_nested_directories_after_failed_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, code: str
) -> None:
    root = _package(tmp_path)
    nested = root / "a-nested"
    nested.mkdir()
    (nested / "a-trigger.txt").write_text("synthetic")
    (nested / "b-later.txt").write_text("must not be read")
    (root / "z-later.txt").write_text("must not be read")
    original = capture._read_regular_bytes
    reads: list[str] = []

    def fail_one(parent_fd: int, name: str, *, byte_limit: int | None = None) -> tuple[bytes, bool]:
        reads.append(name)
        if name == "a-trigger.txt":
            if failure == "changed":
                payload, _ = original(parent_fd, name)
                return payload, False
            if failure == "limit":
                raise capture._CaptureBudgetExceeded("synthetic limit")
            raise OSError("synthetic read failure")
        return original(parent_fd, name, byte_limit=byte_limit)

    monkeypatch.setattr(capture, "_read_regular_bytes", fail_one)
    result = validate_skill_package(root, source_revision="1" * 40)
    assert result.status == "blocked"
    assert code in {finding.code for finding in result.findings}
    assert "a-trigger.txt" in reads
    assert "b-later.txt" not in reads and "z-later.txt" not in reads

    monkeypatch.setattr(capture, "_read_regular_bytes", original)
    assert validate_skill_package(root, source_revision="1" * 40).status == "pass"


def test_incomplete_capture_does_not_claim_unvisited_required_files_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _package(tmp_path)
    oversized = root / "A.txt"
    oversized.write_bytes(b"x" * 129)
    reference = root / "references" / "guide.md"
    reference.parent.mkdir()
    reference.write_text("Available guidance.\n")
    policy = capture.SkillValidationPolicy(required_files=("references/guide.md",), check_reference_content=True)
    monkeypatch.setattr(capture, "_MAX_PACKAGE_FILE_BYTES", 128)

    blocked = validate_skill_package(root, source_revision="1" * 40, policy=policy)
    assert blocked.status == "blocked"
    assert {finding.code for finding in blocked.findings} == {"package_resource_limit"}

    oversized.unlink()
    assert validate_skill_package(root, source_revision="1" * 40, policy=policy).status == "pass"
    reference.unlink()
    missing = validate_skill_package(root, source_revision="1" * 40, policy=policy)
    assert missing.status == "blocked"
    assert "required_file_missing" in {finding.code for finding in missing.findings}


def test_nested_resource_limit_stops_ancestor_reads_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _package(tmp_path)
    nested = root / "a-nested"
    nested.mkdir()
    (nested / "first.txt").write_text("first")
    excess = nested / "second.txt"
    excess.write_text("second")
    (root / "z-later.txt").write_text("must not be read")
    original = capture._read_regular_bytes
    reads: list[str] = []

    def track(parent_fd: int, name: str, *, byte_limit: int | None = None) -> tuple[bytes, bool]:
        reads.append(name)
        return original(parent_fd, name, byte_limit=byte_limit)

    monkeypatch.setattr(capture, "_MAX_PACKAGE_RESOURCES", 4)
    monkeypatch.setattr(capture, "_read_regular_bytes", track)
    blocked = validate_skill_package(root, source_revision="1" * 40)
    assert blocked.status == "blocked"
    assert "package_resource_limit" in {finding.code for finding in blocked.findings}
    assert "z-later.txt" not in reads
    excess.unlink()
    assert validate_skill_package(root, source_revision="1" * 40).status == "pass"
