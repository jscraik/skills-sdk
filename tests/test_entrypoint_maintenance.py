from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from skills_sdk.cli.main import main


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, list[str]]:
    """Create maintained source, runtime target, backup root, and CLI arguments."""
    source = tmp_path / "source" / "example" / "SKILL.md"
    target = tmp_path / "runtime" / "example" / "SKILL.md"
    backup = tmp_path / "backups"
    for parent in (source.parent, target.parent, backup):
        parent.mkdir(parents=True)
    source.write_text("---\nname: example\ndescription: Fixed description.\n---\n\n# Example\n")
    target.write_text("---\nname: example\ndescription: Broken: metadata\n---\n\n# Example\n")
    args = [
        "maintain-entrypoint",
        str(source),
        str(target),
        "--backup-root",
        str(backup),
        "--expected-source",
        hashlib.sha256(source.read_bytes()).hexdigest(),
        "--expected-current",
        hashlib.sha256(target.read_bytes()).hexdigest(),
    ]
    return source, target, backup, args


def test_real_cli_preview_apply_backup_and_idempotence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify preview, explicit repair, backup retention, and idempotence."""
    source, target, backup, args = _fixture(tmp_path)
    before = target.read_bytes()
    neighbor = target.parent / "guide.md"
    neighbor.write_text("Keep this file\n")
    assert main(args) == 2
    assert "repairable" in capsys.readouterr().out
    assert target.read_bytes() == before
    assert list(backup.iterdir()) == []
    assert main([*args, "--apply"]) == 0
    assert target.read_bytes() == source.read_bytes()
    backups = list(backup.iterdir())
    assert len(backups) == 1 and backups[0].read_bytes() == before
    assert neighbor.read_text() == "Keep this file\n"
    assert main([*args, "--apply"]) == 0
    assert list(backup.iterdir()) == backups
    assert sorted(path.name for path in target.parent.iterdir()) == ["SKILL.md", "guide.md"]


@pytest.mark.parametrize("fault", ["source-drift", "target-drift", "malformed", "symlink", "lock", "missing"])
def test_real_cli_refuses_unapproved_or_invalid_state(tmp_path: Path, fault: str) -> None:
    """Verify maintenance refuses drift, malformed paths, locks, and absence."""
    source, target, backup, args = _fixture(tmp_path)
    if fault == "source-drift":
        source.write_text(source.read_text() + "Changed\n")
    elif fault == "target-drift":
        target.write_text("Active writer's work\n")
    elif fault == "malformed":
        source.write_text("---\nname: example\ndescription: Invalid: YAML\n---\n")
        args[args.index("--expected-source") + 1] = hashlib.sha256(source.read_bytes()).hexdigest()
    elif fault == "symlink":
        target.unlink()
        target.symlink_to(source)
    elif fault == "lock":
        (target.parent / ".skills-sdk-entrypoint.lock").write_text("Other operation\n")
    else:
        target.unlink()
    before = target.read_bytes() if target.exists() else None
    assert main([*args, "--apply"]) == 2
    assert (target.read_bytes() if target.exists() else None) == before
    assert list(backup.iterdir()) == []


def test_publication_failure_preserves_current_and_recoverable_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a publication failure preserves current bytes and the backup."""
    from skills_sdk.host import entrypoint

    _source, target, backup, args = _fixture(tmp_path)
    before = target.read_bytes()

    def refuse_exchange(*_args: object, **_kwargs: object) -> None:
        """Inject a publication failure."""
        raise OSError("injected publication failure")

    monkeypatch.setattr(entrypoint, "_exchange", refuse_exchange)
    assert main([*args, "--apply"]) == 2
    assert target.read_bytes() == before
    assert [path.read_bytes() for path in backup.iterdir()] == [before]
    assert [path.name for path in target.parent.iterdir()] == ["SKILL.md"]


def test_writer_racing_publication_is_preserved_in_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a racing writer's bytes remain recoverable in the backup."""
    from skills_sdk.host import entrypoint

    _source, target, backup, args = _fixture(tmp_path)
    exchange = entrypoint._exchange

    def racing_exchange(*positional: object, **keywords: object) -> None:
        """Inject a target write immediately before publication."""
        target.write_text("Concurrent writer bytes\n")
        exchange(*positional, **keywords)

    monkeypatch.setattr(entrypoint, "_exchange", racing_exchange)
    assert main([*args, "--apply"]) == 2
    assert len(list(backup.iterdir())) == 1
    recovery = [path for path in target.parent.iterdir() if path.name.startswith(".skills-sdk-stage-")]
    assert [path.read_text() for path in recovery] == ["Concurrent writer bytes\n"]


def test_replaced_parent_is_not_reported_as_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify replacing the target parent prevents a completed result."""
    from skills_sdk.host import entrypoint

    _source, target, backup, args = _fixture(tmp_path)
    exchange = entrypoint._exchange
    moved = target.parent.with_name("moved-example")

    def racing_exchange(*positional: object, **keywords: object) -> None:
        """Replace the target directory immediately before publication."""
        target.parent.rename(moved)
        target.parent.mkdir()
        target.write_text("Replacement directory writer\n")
        exchange(*positional, **keywords)

    monkeypatch.setattr(entrypoint, "_exchange", racing_exchange)
    assert main([*args, "--apply"]) == 2
    assert target.read_text() == "Replacement directory writer\n"
    assert len(list(backup.iterdir())) == 1


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o750])
def test_repair_preserves_target_permissions(tmp_path: Path, mode: int) -> None:
    """Verify repair and backup retain the target permission bits."""
    _source, target, backup, args = _fixture(tmp_path)
    target.chmod(mode)
    assert main([*args, "--apply"]) == 0
    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert all(stat.S_IMODE(path.stat().st_mode) == mode for path in backup.iterdir())


def test_backup_sync_failure_prevents_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify an unsynced backup prevents replacement publication."""
    from skills_sdk.host import entrypoint

    _source, target, backup, args = _fixture(tmp_path)
    before = target.read_bytes()
    backup_identity = (backup.stat().st_dev, backup.stat().st_ino)
    fsync = os.fsync

    def refuse_backup_sync(descriptor: int) -> None:
        """Inject an fsync failure for the backup directory."""
        observed = os.fstat(descriptor)
        if (observed.st_dev, observed.st_ino) == backup_identity:
            raise OSError("injected backup durability failure")
        fsync(descriptor)

    monkeypatch.setattr(entrypoint.os, "fsync", refuse_backup_sync)
    assert main([*args, "--apply"]) == 2
    assert target.read_bytes() == before
    assert [path.read_bytes() for path in backup.iterdir()] == [before]
    assert [path.name for path in target.parent.iterdir()] == ["SKILL.md"]


@pytest.mark.parametrize(
    "filename, selected, expected", [("guide.md", True, 0), ("guide.md", False, 2), ("run.py", True, 2)]
)
def test_supporting_document_is_explicit_and_bounded(
    tmp_path: Path, filename: str, selected: bool, expected: int
) -> None:
    """Verify supporting-document maintenance is explicit and Markdown-only."""
    source, target, backup, args = _fixture(tmp_path)
    target.write_text("---\nname: example\ndescription: Runtime metadata.\n---\n\n# Example\n")
    original_entrypoint = target.read_bytes()
    document_source, document_target = source.with_name(filename), target.with_name(filename)
    document_source.write_text("Maintained document\n")
    document_target.write_text("Original document\n")
    args[1:3] = [str(document_source), str(document_target)]
    args[args.index("--expected-source") + 1] = hashlib.sha256(document_source.read_bytes()).hexdigest()
    args[args.index("--expected-current") + 1] = hashlib.sha256(document_target.read_bytes()).hexdigest()
    assert main([*args, "--apply", *(["--supporting-document"] if selected else [])]) == expected
    assert target.read_bytes() == original_entrypoint
    assert document_target.read_text() == ("Maintained document\n" if expected == 0 else "Original document\n")
    assert len(list(backup.iterdir())) == (1 if expected == 0 else 0)


def test_supporting_document_requires_runtime_entrypoint(tmp_path: Path) -> None:
    source, target, _backup, args = _fixture(tmp_path)
    document_source, document_target = source.with_name("guide.md"), target.with_name("guide.md")
    document_source.write_text("Maintained document\n")
    document_target.write_text("Original document\n")
    target.unlink()
    args[1:3] = [str(document_source), str(document_target)]
    args[args.index("--expected-source") + 1] = hashlib.sha256(document_source.read_bytes()).hexdigest()
    args[args.index("--expected-current") + 1] = hashlib.sha256(document_target.read_bytes()).hexdigest()
    assert main([*args, "--apply", "--supporting-document", "--json"]) == 2


@pytest.mark.parametrize("tree", ["source", "runtime"])
def test_backup_root_inside_package_tree_is_blocked(tmp_path: Path, tree: str) -> None:
    source, target, _backup, args = _fixture(tmp_path)
    nested = (source.parent if tree == "source" else target.parent) / "backups"
    nested.mkdir()
    args[args.index("--backup-root") + 1] = str(nested)
    assert main([*args, "--apply", "--json"]) == 2


def test_backup_is_an_independent_snapshot(tmp_path: Path) -> None:
    _source, target, backup, args = _fixture(tmp_path)
    alias = target.with_name("alias.md")
    os.link(target, alias)
    before = target.read_bytes()
    assert main([*args, "--apply"]) == 0
    alias.write_text("Alias mutation\n")
    assert [path.read_bytes() for path in backup.iterdir()] == [before]


def test_json_failure_is_typed_and_versioned(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _source, _target, _backup, args = _fixture(tmp_path)
    args[args.index("--expected-current") + 1] = "0" * 64
    assert main([*args, "--apply", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "entrypoint-maintenance-result/v1"
    assert payload["status"] == "blocked"
    assert payload["blocker"]["code"] == "entrypoint_maintenance_blocked"
