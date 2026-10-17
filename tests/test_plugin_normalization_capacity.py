"""Pre-write normalization capacity and path-resolution regression boundaries."""

from __future__ import annotations

import json
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

import pytest
from test_plugin_normalization import FIXTURE_ROOT, _context, _normalize

from skills_sdk.cli.main import main
from skills_sdk.core.schema_registry import SchemaRegistry


def _normalization_command(source: Path, destination: Path, context: Path) -> list[str]:
    """Use the supported CLI with the same metadata as the public API fixture."""
    return [
        "normalize-plugin",
        str(source),
        str(destination),
        "--context",
        str(context),
        "--plugin-name",
        "synthetic-plugin",
        "--plugin-version",
        "1.0.0",
        "--plugin-description",
        "Synthetic one-skill plugin fixture.",
        "--json",
        "--robot",
    ]


@pytest.mark.parametrize("mode", [0o702, 0o720, 0o722])
def test_normalization_rejects_shared_writable_parent_and_recovers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: int
) -> None:
    """Reject visibly shared parent permissions before writing through API and CLI."""
    source, parent = tmp_path / "synthetic-skill", tmp_path / "output"
    shutil.copytree(FIXTURE_ROOT, source)
    parent.mkdir()
    parent.chmod(mode)
    context = tmp_path / "context.json"
    context.write_text(_context().model_dump_json(), encoding="utf-8")
    try:
        rejected = _normalize(source, parent / "plugin")
        assert rejected.status == "blocked" and not rejected.candidate_created
        assert rejected.blocker is not None and rejected.blocker.code == "candidate_normalization_failed"
        assert main(_normalization_command(source, parent / "cli-plugin", context)) == 2
        assert not json.loads(capsys.readouterr().out)["candidate_created"]
        assert list(parent.iterdir()) == []
    finally:
        parent.chmod(0o700)
    assert _normalize(source, parent / "plugin").status == "prepared"
    assert main(_normalization_command(source, parent / "cli-plugin", context)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "prepared"


@pytest.mark.parametrize("mutual", [False, True])
def test_normalization_symlink_loop_blocks_api_cli_and_recovers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutual: bool
) -> None:
    """Return typed pre-write blockers for real path loops, then accept a corrected parent."""
    tmp_path = tmp_path.resolve(strict=True)
    source, parent = tmp_path / "synthetic-skill", tmp_path / "loop"
    shutil.copytree(FIXTURE_ROOT, source)
    original = (source / "SKILL.md").read_bytes()
    target = tmp_path / "other-loop" if mutual else parent
    parent.symlink_to(target, target_is_directory=True)
    if mutual:
        target.symlink_to(parent, target_is_directory=True)
    rejected = _normalize(source, parent / "plugin")
    assert rejected.status == "blocked" and not rejected.candidate_created
    assert rejected.blocker is not None and rejected.blocker.code == "candidate_normalization_failed"
    context = tmp_path / "context.json"
    context.write_text(_context().model_dump_json(), encoding="utf-8")
    assert main(_normalization_command(source, parent / "cli-plugin", context)) == 2
    output = capsys.readouterr()
    assert not output.err and "Traceback" not in output.out
    payload = json.loads(output.out)
    assert not payload["candidate_created"] and payload["blocker"]["code"] == rejected.blocker.code
    SchemaRegistry().validate("plugin-normalization.v1", payload)
    assert parent.is_symlink() and (source / "SKILL.md").read_bytes() == original
    parent.unlink()
    if mutual:
        target.unlink()
    parent.mkdir()
    recovered = _normalize(source, parent / "plugin")
    assert recovered.status == "prepared" and recovered.source_intake.candidate == rejected.source_intake.candidate
    assert main(_normalization_command(source, parent / "cli-plugin", context)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "prepared"
    assert (source / "SKILL.md").read_bytes() == original


@pytest.mark.parametrize("limit", ["MAX_FILES", "MAX_TOTAL_BYTES", "MAX_RESOURCES", "MAX_DEPTH"])
def test_normalization_reserves_wrapper_capacity_and_corrects_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], limit: str
) -> None:
    """Reject raw-fit source before copying and accept corrected input exactly at each output bound."""
    from skills_sdk.models.plugin_normalization import _canonical_normalization_manifest
    from skills_sdk.validation import plugin_capture

    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    (source / "asset.bin").write_bytes(b"x")
    (source / "empty" / "nested").mkdir(parents=True)
    files, _, directories = plugin_capture.capture_plugin_source(source)
    manifest = _canonical_normalization_manifest("synthetic-plugin", "1.0.0", "Synthetic one-skill plugin fixture.")
    bounds = {
        "MAX_FILES": len(files) + 1,
        "MAX_TOTAL_BYTES": sum(item.size_bytes for item in files) + len(manifest),
        "MAX_RESOURCES": len(files) + len(directories) + 3,
        "MAX_DEPTH": 4,
    }
    monkeypatch.setattr(plugin_capture, limit, bounds[limit])
    overflow = source / "overflow.bin"
    if limit == "MAX_DEPTH":
        (source / "empty" / "nested" / "deeper").mkdir()
        overflow = source / "empty" / "nested" / "deeper" / "overflow.bin"
    overflow.write_bytes(b"x")
    # The raw source fits: only its complete wrapped output exceeds the selected bound.
    plugin_capture.capture_plugin_source(source)
    rejected = _normalize(source, tmp_path / "blocked-plugin")
    assert rejected.status == "blocked" and not rejected.candidate_created
    assert rejected.blocker is not None and rejected.blocker.code == "standalone_source_capacity_exceeded"
    assert rejected.plugin_validation is None and not (tmp_path / "blocked-plugin").exists()
    context = tmp_path / "context.json"
    context.write_text(_context().model_dump_json(), encoding="utf-8")
    assert main(_normalization_command(source, tmp_path / "blocked-cli", context)) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["blocker"]["code"] == rejected.blocker.code and not payload["candidate_created"]
    assert not (tmp_path / "blocked-cli").exists() and overflow.read_bytes() == b"x"
    SchemaRegistry().validate("plugin-normalization.v1", payload)
    overflow.unlink()
    if limit == "MAX_DEPTH":
        overflow.parent.rmdir()
    recovered = _normalize(source, tmp_path / "recovered-plugin")
    assert recovered.status == "prepared" and recovered.plugin_validation is not None
    assert recovered.source_intake.candidate != rejected.source_intake.candidate
    assert recovered.plugin_validation.skills[0].validation.candidate == recovered.source_intake.candidate
    assert main(_normalization_command(source, tmp_path / "recovered-cli", context)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "prepared"


@pytest.mark.parametrize("nested", [False, True])
def test_normalization_rejects_physical_source_ancestry_despite_lexical_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], nested: bool
) -> None:
    """Descriptor identity rejects source containment even when host resolution spells an alias differently."""
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    parent = source
    if nested:
        parent = source / "nested"
        parent.mkdir()
    original = (source / "SKILL.md").read_bytes()
    resolve = Path.resolve

    def lexical_alias(path: Path, strict: bool = False) -> Path:
        """Model a case-insensitive host's alternate spelling without changing real directory identities."""
        return source.with_name("SYNTHETIC-SKILL") if path == source else resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", lexical_alias)
    rejected = _normalize(source, parent / "plugin")
    assert rejected.status == "blocked" and not rejected.candidate_created
    assert rejected.blocker is not None and rejected.blocker.code == "candidate_normalization_failed"
    assert not (parent / "plugin").exists()
    context = tmp_path / "context.json"
    context.write_text(_context().model_dump_json(), encoding="utf-8")
    assert main(_normalization_command(source, parent / "cli-plugin", context)) == 2
    payload = json.loads(capsys.readouterr().out)
    assert not payload["candidate_created"] and payload["source_mutated"] is False
    assert payload["blocker"]["code"] == rejected.blocker.code and not (parent / "cli-plugin").exists()
    SchemaRegistry().validate("plugin-normalization.v1", payload)
    recovered = _normalize(source, tmp_path / "outside-plugin")
    assert recovered.status == "prepared" and recovered.source_intake.candidate == rejected.source_intake.candidate
    assert main(_normalization_command(source, tmp_path / "outside-cli", context)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "prepared"
    assert (source / "SKILL.md").read_bytes() == original


def test_normalization_rejects_setgid_parent_before_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject inherited special modes before creating a partial candidate."""
    source = tmp_path.resolve() / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    parent = tmp_path.resolve() / "shared"
    parent.mkdir()
    original = parent.stat()
    fstat = os.fstat

    def shared_parent_stat(descriptor: int) -> os.stat_result:
        info = fstat(descriptor)
        if (info.st_dev, info.st_ino) == (original.st_dev, original.st_ino):
            fields = list(info)
            fields[0] |= stat.S_ISGID
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(os, "fstat", shared_parent_stat)
    receipt = _normalize(source, parent / "plugin")

    assert receipt.status == "blocked" and not receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "candidate_normalization_failed"
    assert list(parent.iterdir()) == []
    assert stat.S_IMODE(parent.stat().st_mode) == stat.S_IMODE(original.st_mode)
    assert (source / "SKILL.md").read_bytes() == (FIXTURE_ROOT / "SKILL.md").read_bytes()
    assert _normalize(source, tmp_path.resolve() / "ordinary-plugin").status == "prepared"


@pytest.mark.parametrize("mask", [0o111, 0o222])
def test_normalization_restores_created_directory_modes_under_umask(tmp_path: Path, mask: int) -> None:
    """Restrictive process umasks cannot leave a partial or inaccessible candidate."""
    source = tmp_path.resolve() / "synthetic-skill"
    destination = tmp_path.resolve() / "plugin"
    shutil.copytree(FIXTURE_ROOT, source)
    previous = os.umask(mask)
    try:
        receipt = _normalize(source, destination)
    finally:
        os.umask(previous)

    assert receipt.status == "prepared" and receipt.candidate_created
    for path in (destination, destination / "skills", destination / "skills" / "synthetic-skill"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o755
    assert (source / "SKILL.md").read_bytes() == (FIXTURE_ROOT / "SKILL.md").read_bytes()


def test_normalization_captures_retained_directory_during_path_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean pathname clone cannot hide changed bytes in the directory actually created."""
    from skills_sdk.intake import plugin_normalization as normalization

    source = tmp_path.resolve() / "synthetic-skill"
    destination = tmp_path.resolve() / "plugin"
    shutil.copytree(FIXTURE_ROOT, source)
    original_path_capture = normalization.capture_plugin_source
    original_descriptor_capture = normalization._capture_plugin_descriptor
    attacked = False

    def swap_for_capture(capture: Callable[[], tuple]) -> tuple:
        nonlocal attacked
        if attacked:
            return capture()
        attacked = True
        retained = tmp_path / "retained-original"
        destination.rename(retained)
        shutil.copytree(retained, destination)
        (retained / "skills" / "synthetic-skill" / "SKILL.md").write_bytes(b"changed after validation\n")
        try:
            return capture()
        finally:
            shutil.rmtree(destination)
            retained.rename(destination)

    def path_capture(root: Path) -> tuple:
        if root == destination:
            return swap_for_capture(lambda: original_path_capture(root))
        return original_path_capture(root)

    def descriptor_capture(descriptor: int) -> tuple:
        return swap_for_capture(lambda: original_descriptor_capture(descriptor))

    with monkeypatch.context() as patch:
        patch.setattr(normalization, "capture_plugin_source", path_capture)
        patch.setattr(normalization, "_capture_plugin_descriptor", descriptor_capture)
        receipt = _normalize(source, destination)

    assert attacked
    assert receipt.status == "blocked" and receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "normalized_candidate_changed"
    assert receipt.normalized_package is None
    assert (source / "SKILL.md").read_bytes() == (FIXTURE_ROOT / "SKILL.md").read_bytes()
    assert _normalize(source, tmp_path / "recovered-plugin").status == "prepared"
