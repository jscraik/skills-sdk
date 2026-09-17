from __future__ import annotations

import builtins
import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path

import pytest

from skills_sdk.cli.main import main
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models import EntrypointMaintenanceBlocker, EntrypointMaintenanceResult, RuntimeCopyComparison


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


def _backup_files(backup: Path) -> list[Path]:
    return [path for path in backup.iterdir() if not path.name.endswith(".lock")]


def test_real_cli_preview_apply_backup_and_idempotence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify preview, explicit repair, backup retention, and idempotence."""
    source, target, backup, args = _fixture(tmp_path)
    before = target.read_bytes()
    neighbor = target.parent / "guide.md"
    neighbor.write_text("Keep this file\n")
    assert main(args) == 2
    assert "repairable" in capsys.readouterr().out
    assert target.read_bytes() == before
    assert _backup_files(backup) == []
    assert main([*args, "--apply"]) == 0
    assert target.read_bytes() == source.read_bytes()
    backups = _backup_files(backup)
    assert len(backups) == 2 and all(path.read_bytes() == before for path in backups)
    assert neighbor.read_text() == "Keep this file\n"
    assert main([*args, "--apply"]) == 0
    assert _backup_files(backup) == backups
    assert sorted(path.name for path in target.parent.iterdir()) == ["SKILL.md", "guide.md"]


@pytest.mark.parametrize("fault", ["source-drift", "target-drift", "malformed", "symlink", "missing"])
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
    else:
        target.unlink()
    before = target.read_bytes() if target.exists() else None
    assert main([*args, "--apply"]) == 2
    assert (target.read_bytes() if target.exists() else None) == before
    assert _backup_files(backup) == []


def test_live_advisory_lock_blocks_maintenance(tmp_path: Path) -> None:
    """Verify a live writer blocks while a stale lock pathname remains reusable."""
    _source, target, backup, args = _fixture(tmp_path)
    from skills_sdk.host.entrypoint import _LOCK_ROOT, _lock_name

    target_parent = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        lock_path = _LOCK_ROOT / _lock_name(target_parent, target.name)
    finally:
        os.close(target_parent)
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert main([*args, "--apply"]) == 2
        assert _backup_files(backup) == []
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    assert main([*args, "--apply"]) == 0


def test_non_regular_lock_is_rejected_without_blocking(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable")
    _source, target, _backup, args = _fixture(tmp_path)
    from skills_sdk.host.entrypoint import _LOCK_ROOT, _lock_name

    target_parent = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        lock_path = _LOCK_ROOT / _lock_name(target_parent, target.name)
    finally:
        os.close(target_parent)
    lock_path.unlink(missing_ok=True)
    os.mkfifo(lock_path)
    try:
        assert main([*args, "--apply", "--json"]) == 2
    finally:
        lock_path.unlink()


def test_lock_namespace_is_independent_of_alias_and_backup_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify target aliases and alternate backup roots serialize one repair."""
    from skills_sdk.host.entrypoint import _LOCK_ROOT, _lock_name

    _source, target, _backup, args = _fixture(tmp_path)
    alternate_backup = tmp_path / "alternate-backups"
    alternate_backup.mkdir()
    monkeypatch.chdir(tmp_path)
    args[2] = str(target.relative_to(tmp_path))
    args[args.index("--backup-root") + 1] = str(alternate_backup)
    target_parent = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        lock_path = _LOCK_ROOT / _lock_name(target_parent, target.name)
    finally:
        os.close(target_parent)
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert main([*args, "--apply"]) == 2
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def test_cross_device_backup_root_is_rejected_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skills_sdk.host import entrypoint

    _source, target, backup, args = _fixture(tmp_path)
    before = target.read_bytes()
    backup_inode = backup.stat().st_ino
    real_fstat = os.fstat

    def cross_device_fstat(descriptor: int) -> os.stat_result:
        observed = real_fstat(descriptor)
        if observed.st_ino != backup_inode:
            return observed
        values = list(observed)
        values[2] = observed.st_dev + 1
        return os.stat_result(values)

    monkeypatch.setattr(entrypoint.os, "fstat", cross_device_fstat)
    assert main([*args, "--apply", "--json"]) == 2
    assert target.read_bytes() == before
    assert _backup_files(backup) == []


def test_unsupported_host_adapter_import_is_a_typed_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _source, _target, _backup, args = _fixture(tmp_path)
    real_import = builtins.__import__

    def guarded_import(name: str, *positional: object, **keywords: object) -> object:
        if name == "skills_sdk.host.entrypoint":
            raise ModuleNotFoundError("unsupported host")
        return real_import(name, *positional, **keywords)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert main([*args, "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_maintenance_models_are_exported_from_facade() -> None:
    assert EntrypointMaintenanceBlocker.__name__ == "EntrypointMaintenanceBlocker"
    assert EntrypointMaintenanceResult.__name__ == "EntrypointMaintenanceResult"
    assert RuntimeCopyComparison.__name__ == "RuntimeCopyComparison"


def test_registry_normalizes_mapping_before_model_validation() -> None:
    class ProxyMapping(Mapping[str, object]):
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __getitem__(self, key: str) -> object:
            return self.payload[key]

        def __iter__(self):
            return iter(self.payload)

        def __len__(self) -> int:
            return len(self.payload)

    result = EntrypointMaintenanceResult(status="blocked", blocker=EntrypointMaintenanceBlocker(code="x", message="x"))
    SchemaRegistry().validate("entrypoint-maintenance-result.v1", ProxyMapping(result.model_dump(mode="json")))


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
    snapshots = [path for path in _backup_files(backup) if path.suffix == ".bak"]
    assert [path.read_bytes() for path in snapshots] == [before]
    assert sorted(path.name for path in target.parent.iterdir()) == ["SKILL.md"]


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
    assert len(_backup_files(backup)) >= 1
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
    assert len(_backup_files(backup)) >= 1


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o750])
def test_repair_preserves_target_permissions(tmp_path: Path, mode: int) -> None:
    """Verify repair and backup retain the target permission bits."""
    _source, target, backup, args = _fixture(tmp_path)
    target.chmod(mode)
    assert main([*args, "--apply"]) == 0
    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert all(stat.S_IMODE(path.stat().st_mode) == mode for path in _backup_files(backup))


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
    assert [path.read_bytes() for path in _backup_files(backup)] == [before]
    assert sorted(path.name for path in target.parent.iterdir()) == ["SKILL.md"]


def test_post_exchange_sync_failure_is_indeterminate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify post-publication durability failure retains both recovery copies."""
    from skills_sdk.host import entrypoint

    source, target, backup, args = _fixture(tmp_path)
    target_parent_identity = (target.parent.stat().st_dev, target.parent.stat().st_ino)
    fsync = os.fsync

    def refuse_published_parent_sync(descriptor: int) -> None:
        observed = os.fstat(descriptor)
        if stat.S_ISDIR(observed.st_mode) and (observed.st_dev, observed.st_ino) == target_parent_identity:
            raise OSError("injected publication durability failure")
        fsync(descriptor)

    monkeypatch.setattr(entrypoint.os, "fsync", refuse_published_parent_sync)
    assert main([*args, "--apply", "--json"]) == 2
    assert target.read_bytes() == source.read_bytes()
    assert len(_backup_files(backup)) >= 1
    assert len([path for path in target.parent.iterdir() if path.name.startswith(".skills-sdk-stage-")]) == 1


def test_recursive_frontmatter_is_a_typed_blocker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from skills_sdk.host import entrypoint

    _source, target, backup, args = _fixture(tmp_path)
    before = target.read_bytes()

    def recursive_frontmatter(_text: str) -> object:
        raise RecursionError("injected recursive YAML")

    monkeypatch.setattr(entrypoint, "read_frontmatter", recursive_frontmatter)
    assert main([*args, "--apply", "--json"]) == 2
    assert target.read_bytes() == before
    assert _backup_files(backup) == []


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
    assert len(_backup_files(backup)) == (2 if expected == 0 else 0)


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
    assert main([*args, "--json"]) == 2
    assert main([*args, "--apply", "--json"]) == 2


@pytest.mark.parametrize("fault", ["executable", "non_utf8", "nul"])
def test_supporting_document_rejects_unsafe_content(tmp_path: Path, fault: str) -> None:
    source, target, backup, args = _fixture(tmp_path)
    target.write_text("---\nname: example\ndescription: Runtime metadata.\n---\n\n# Example\n")
    document_source, document_target = source.with_name("guide.md"), target.with_name("guide.md")
    document_source.write_text("Maintained document\n")
    document_target.write_text("Original document\n")
    if fault == "executable":
        document_source.chmod(0o755)
    elif fault == "non_utf8":
        document_source.write_bytes(b"\xff\xfe")
    else:
        document_source.write_bytes(b"text\x00payload")
    args[1:3] = [str(document_source), str(document_target)]
    args[args.index("--expected-source") + 1] = hashlib.sha256(document_source.read_bytes()).hexdigest()
    args[args.index("--expected-current") + 1] = hashlib.sha256(document_target.read_bytes()).hexdigest()
    assert main([*args, "--apply", "--supporting-document", "--json"]) == 2
    assert document_target.read_text() == "Original document\n"
    assert _backup_files(backup) == []


def test_special_permission_bits_are_not_republished(tmp_path: Path) -> None:
    _source, target, backup, args = _fixture(tmp_path)
    target.chmod(0o4755)
    assert main([*args, "--apply"]) == 0
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    snapshots = [path for path in _backup_files(backup) if path.suffix == ".bak"]
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o755 for path in snapshots)


def test_backup_is_an_independent_snapshot(tmp_path: Path) -> None:
    _source, target, backup, args = _fixture(tmp_path)
    alias = target.with_name("alias.md")
    os.link(target, alias)
    before = target.read_bytes()
    assert main([*args, "--apply"]) == 0
    alias.write_text("Alias mutation\n")
    snapshots = [path for path in _backup_files(backup) if path.suffix == ".bak"]
    assert [path.read_bytes() for path in snapshots] == [before]


def test_json_failure_is_typed_and_versioned(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _source, _target, _backup, args = _fixture(tmp_path)
    args[args.index("--expected-current") + 1] = "0" * 64
    assert main([*args, "--apply", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "entrypoint-maintenance-result/v1"
    assert payload["status"] == "blocked"
    assert payload["blocker"]["code"] == "entrypoint_maintenance_blocked"
    SchemaRegistry().validate("entrypoint-maintenance-result.v1", payload)
    payload["blocker"] = None
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("entrypoint-maintenance-result.v1", payload)
