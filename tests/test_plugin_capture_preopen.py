"""Pre-open type checks for portable-plugin source capture."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI
from skills_sdk.validation import plugin_capture, skill_package
from skills_sdk.validation.plugin_capture import capture_plugin_source
from skills_sdk.validation.plugin_package import validate_plugin_package
from skills_sdk.validation.skill_package import validate_skill_package

REVISION = "1" * 40
FILE_TYPES = [stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFLNK]
FILE_TYPE_IDS = ["character", "block", "fifo", "socket", "symlink"]


def _fixture(tmp_path: Path) -> Path:
    """Create one minimal valid portable-plugin source tree."""
    root = tmp_path.resolve() / "plugin"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"$schema": PLUGIN_SCHEMA_URI, "name": "fixture-plugin"}),
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize(
    "file_type",
    FILE_TYPES,
    ids=FILE_TYPE_IDS,
)
def test_known_nonregular_type_is_rejected_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_type: int,
) -> None:
    """Reject a known nonregular plugin entry before its reader is called."""
    root = _fixture(tmp_path)
    real_stat = plugin_capture.os.stat
    real_read_file = plugin_capture._read_file
    opened: list[str] = []

    def synthetic_stat(path: str, *args: object, **kwargs: object) -> object:
        """Report the target entry as a synthetic prohibited file type."""
        if path == "plugin.json":
            return SimpleNamespace(st_mode=file_type | 0o600, st_size=1)
        return real_stat(path, *args, **kwargs)

    def opener_spy(parent: int, name: str) -> tuple[bytes, int]:
        """Record any unsafe attempt to pass the target to the reader."""
        opened.append(name)
        raise AssertionError("known nonregular source reached the file opener")

    monkeypatch.setattr(plugin_capture.os, "stat", synthetic_stat)
    monkeypatch.setattr(plugin_capture, "_read_file", opener_spy)
    rejected = validate_plugin_package(root, source_revision=REVISION)
    assert rejected.status == "blocked"
    assert rejected.findings[0].code == "plugin_input_invalid"
    assert rejected.findings[0].message == "plugin source requires bounded ordinary files and safe no-follow paths"
    assert opened == []

    monkeypatch.setattr(plugin_capture.os, "stat", real_stat)
    monkeypatch.setattr(plugin_capture, "_read_file", real_read_file)
    recovered = validate_plugin_package(root, source_revision=REVISION)
    assert recovered.status == "pass"
    assert not recovered.execution_authorized and not recovered.release_ready and not recovered.mutation_performed


@pytest.mark.parametrize("file_type", FILE_TYPES, ids=FILE_TYPE_IDS)
def test_standalone_known_nonregular_type_is_rejected_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_type: int,
) -> None:
    """Reject a known nonregular standalone entry before opening it."""
    root = tmp_path.resolve() / "fixture-skill"
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: Synthetic fixture.\n---\n# Fixture\n",
        encoding="utf-8",
    )
    real_stat = skill_package.os.stat
    real_open = skill_package.os.open
    real_supports_dir_fd = skill_package.os.supports_dir_fd
    opened: list[str] = []

    def synthetic_stat(path: str, *args: object, **kwargs: object) -> object:
        """Report the standalone entry as a synthetic prohibited type."""
        if path == "SKILL.md":
            return SimpleNamespace(st_mode=file_type | 0o600, st_size=1)
        return real_stat(path, *args, **kwargs)

    def open_spy(path: str | bytes | int, flags: int, *args: object, **kwargs: object) -> int:
        """Trap only the target file while preserving safe directory opens."""
        if path == "SKILL.md":
            opened.append(path)
            raise AssertionError("known nonregular source reached the file opener")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(skill_package.os, "stat", synthetic_stat)
    monkeypatch.setattr(skill_package.os, "open", open_spy)
    monkeypatch.setattr(skill_package.os, "supports_dir_fd", {*real_supports_dir_fd, open_spy})
    rejected = validate_skill_package(root, source_revision=REVISION)
    assert rejected.status == "blocked"
    assert "unreadable_package_file" in {item.code for item in rejected.findings}
    assert opened == []

    monkeypatch.setattr(skill_package.os, "stat", real_stat)
    monkeypatch.setattr(skill_package.os, "open", real_open)
    monkeypatch.setattr(skill_package.os, "supports_dir_fd", real_supports_dir_fd)
    recovered = validate_skill_package(root, source_revision=REVISION)
    assert recovered.status == "pass"
    assert not recovered.mutation_performed


@pytest.mark.parametrize("phase", ["first", "later"])
def test_post_open_type_change_remains_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str) -> None:
    """Retain descriptor checks when a plugin entry changes type after stat."""
    root = _fixture(tmp_path)
    real_metadata = plugin_capture._metadata
    real_read = plugin_capture.os.read
    regular_observations = 0
    read_calls = 0

    def changing_metadata(descriptor: int) -> tuple[int, ...]:
        """Expose a prohibited descriptor type at the selected race phase."""
        nonlocal regular_observations
        value = real_metadata(descriptor)
        if stat.S_ISREG(value[2]):
            regular_observations += 1
            if phase == "first" or regular_observations > 1:
                return (*value[:2], stat.S_IFIFO | stat.S_IMODE(value[2]), *value[3:])
        return value

    def read_spy(descriptor: int, size: int) -> bytes:
        """Count reads while delegating ordinary file access unchanged."""
        nonlocal read_calls
        read_calls += 1
        return real_read(descriptor, size)

    monkeypatch.setattr(plugin_capture, "_metadata", changing_metadata)
    monkeypatch.setattr(plugin_capture.os, "read", read_spy)
    with pytest.raises(ValueError, match=r"ordinary regular-file|source changed during capture"):
        capture_plugin_source(root)
    assert regular_observations == (1 if phase == "first" else 2)
    assert (read_calls == 0) if phase == "first" else (read_calls > 0)

    monkeypatch.setattr(plugin_capture, "_metadata", real_metadata)
    monkeypatch.setattr(plugin_capture.os, "read", real_read)
    recovered = validate_plugin_package(root, source_revision=REVISION)
    assert recovered.status == "pass"


def test_standalone_post_open_type_change_remains_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject a standalone entry whose opened descriptor changes type."""
    root = tmp_path.resolve() / "fixture-skill"
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: Synthetic fixture.\n---\n# Fixture\n",
        encoding="utf-8",
    )
    real_fstat = skill_package.os.fstat
    regular_observations = 0

    def changed_descriptor_type(descriptor: int) -> object:
        """Expose a FIFO mode only after the standalone file is opened."""
        nonlocal regular_observations
        value = real_fstat(descriptor)
        if stat.S_ISREG(value.st_mode):
            regular_observations += 1
            values = list(value)
            values[stat.ST_MODE] = stat.S_IFIFO | stat.S_IMODE(value.st_mode)
            return type(value)(values)
        return value

    monkeypatch.setattr(skill_package.os, "fstat", changed_descriptor_type)
    rejected = validate_skill_package(root, source_revision=REVISION)
    assert rejected.status == "blocked"
    assert "unreadable_package_file" in {item.code for item in rejected.findings}
    assert regular_observations == 1

    monkeypatch.setattr(skill_package.os, "fstat", real_fstat)
    assert validate_skill_package(root, source_revision=REVISION).status == "pass"
