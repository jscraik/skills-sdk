"""Resource-boundary regressions for untrusted standalone package intake."""

from pathlib import Path

import pytest

from skills_sdk.packaging import build_skill_package
from skills_sdk.validation import skill_package as capture
from skills_sdk.validation import validate_skill_package


def _package(tmp_path: Path) -> Path:
    root = tmp_path / "bounded-skill"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: bounded-skill\ndescription: Safe fixture.\n---\nDo work.\n")
    return root


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


@pytest.mark.parametrize("limit", ["_MAX_PACKAGE_FILE_BYTES", "_MAX_PACKAGE_TOTAL_BYTES"])
def test_capture_byte_limits_block_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str) -> None:
    root = _package(tmp_path)
    (root / "resource.txt").write_bytes(b"x" * 257)
    monkeypatch.setattr(capture, limit, 256, raising=False)
    result = build_skill_package(root, source_revision="1" * 40)
    assert result.status == "blocked"
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
    (root / "resource.txt").write_bytes(b"x")
    original_read = capture.os.read
    reads = 0

    def growing_read(descriptor: int, size: int) -> bytes:
        nonlocal reads
        if capture.os.fstat(descriptor).st_size == 1:
            reads += 1
            assert reads <= 2, "capture must stop before the third read"
            return b"x" * min(size, 200)
        return original_read(descriptor, size)

    monkeypatch.setattr(capture, "_MAX_PACKAGE_FILE_BYTES", 256)
    monkeypatch.setattr(capture.os, "read", growing_read)
    result = validate_skill_package(root, source_revision="1" * 40)
    assert result.status == "blocked"
    assert reads == 2


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
