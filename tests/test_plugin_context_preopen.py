"""Evidence file readers reject known special files before opening the leaf."""

from __future__ import annotations

import importlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI, PluginValidationPolicy
from skills_sdk.validation import validate_plugin_package

cli = importlib.import_module("skills_sdk.cli.main")
REVISION = "1" * 40


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Save ordinary valid plugin evidence outside the source tree."""
    root = tmp_path.resolve() / "plugin"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"$schema": PLUGIN_SCHEMA_URI, "name": "fixture", "version": "1.0.0"}), encoding="utf-8"
    )
    result = validate_plugin_package(
        root, source_revision=REVISION, policy=PluginValidationPolicy(require_version=True)
    )
    assert result.status == "pass"
    evidence = root.parent / "evidence.json"
    evidence.write_text(result.model_dump_json(), encoding="utf-8")
    return root, evidence


@pytest.mark.parametrize("mode", [stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFLNK, stat.S_IFDIR])
def test_evidence_leaf_type_is_checked_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: int
) -> None:
    """Prove no unsafe leaf opens, typed policy retention and corrected-input recovery."""
    root, evidence = _fixture(tmp_path)
    real_stat, real_open = os.stat, os.open
    opened: list[str] = []

    def synthetic_stat(path: object, *args: object, **kwargs: object) -> object:
        """Give the leaf an unsafe type without creating or touching a device."""
        if path == evidence.name:
            assert kwargs["follow_symlinks"] is False and isinstance(kwargs["dir_fd"], int)
            return SimpleNamespace(st_mode=mode | 0o600)
        return real_stat(path, *args, **kwargs)

    def open_spy(path: object, flags: int, *args: object, **kwargs: object) -> int:
        """Record only the leaf open; directory traversal remains real."""
        if path == evidence.name:
            opened.append(evidence.name)
        return real_open(path, flags, *args, **kwargs)

    arguments = [
        "validate-plugin",
        str(root),
        "--source-revision",
        REVISION,
        "--verify-evidence",
        str(evidence),
        "--require-version",
        "--json",
        "--robot",
    ]
    with monkeypatch.context() as patch:
        patch.setattr(os, "stat", synthetic_stat)
        patch.setattr(os, "open", open_spy)
        patch.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, synthetic_stat, open_spy})
        patch.setattr(os, "supports_follow_symlinks", {*os.supports_follow_symlinks, synthetic_stat})
        assert cli.main(arguments) == 2
    result = json.loads(capsys.readouterr().out)
    assert opened == []
    assert result["findings"][0]["code"] == "plugin_evidence_invalid"
    assert result["policy"]["require_version"] is True
    assert not any(result[key] for key in ("mutation_performed", "execution_authorized", "release_ready"))
    assert cli.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


def test_context_post_open_check_still_rejects_type_races(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject a nonregular descriptor before reading and always close it."""
    _, evidence = _fixture(tmp_path)
    real_fstat, real_read, real_close = os.fstat, os.read, os.close
    rejected: list[int] = []
    closed: list[int] = []

    def changed_type(descriptor: int) -> object:
        """Present a changed leaf type only at the post-open boundary."""
        value = real_fstat(descriptor)
        if stat.S_ISREG(value.st_mode):
            rejected.append(descriptor)
            return SimpleNamespace(st_mode=stat.S_IFCHR)
        return value

    def read_spy(descriptor: int, size: int) -> bytes:
        """Ensure the rejected descriptor is never read."""
        assert descriptor not in rejected
        return real_read(descriptor, size)

    def close_spy(descriptor: int) -> None:
        """Retain real descriptor closure while collecting the closed handles."""
        closed.append(descriptor)
        real_close(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", changed_type)
        patch.setattr(os, "read", read_spy)
        patch.setattr(os, "close", close_spy)
        with pytest.raises(ValueError, match="invalid intake context file"):
            cli._read_intake_context(evidence)
    assert len(rejected) == 1 and rejected[0] in closed
    assert cli._read_intake_context(evidence) == evidence.read_bytes()


@pytest.mark.parametrize("capability", ["supports_dir_fd", "supports_follow_symlinks"])
def test_missing_safe_stat_support_blocks_before_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capability: str
) -> None:
    """Return the existing unsupported-host exception before opening any path."""
    _, evidence = _fixture(tmp_path)
    opened: list[object] = []

    def unexpected_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        """Trap traversal when safe no-follow stat is unavailable."""
        opened.append(path)
        raise AssertionError("unsupported context read opened a path")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", unexpected_open)
        patch.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, unexpected_open})
        patch.setattr(os, capability, getattr(os, capability) - {os.stat})
        with pytest.raises(cli._UnsupportedContextRead):
            cli._read_intake_context(evidence)
    assert opened == []
    assert cli._read_intake_context(evidence) == evidence.read_bytes()
