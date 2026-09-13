"""Digest-bound maintenance of an existing host SKILL.md, never package install."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from yaml import YAMLError

from skills_sdk.validation.skill_ir import read_frontmatter
from skills_sdk.validation.skill_package import _open_directory_tree


class EntrypointRequest(BaseModel):
    """Local-only host arguments; never a portable receipt or authorization grant."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    source: Path
    target: Path
    backup_root: Path
    expected_source: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_current: str = Field(pattern=r"^[a-f0-9]{64}$")
    supporting_document: bool = False


@dataclass(frozen=True, slots=True)
class CapturedFile:
    data: bytes
    digest: str
    device: int
    inode: int
    mode: int


def _capture(parent: int, name: str) -> CapturedFile:
    descriptor = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 8 * 1024 * 1024:
            raise ValueError("entrypoint must be a regular file no larger than 8 MiB")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(8 * 1024 * 1024 + 1)
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(data) != before.st_size:
            raise ValueError("entrypoint changed during capture")
        return CapturedFile(data, hashlib.sha256(data).hexdigest(), before.st_dev, before.st_ino, before.st_mode)
    finally:
        os.close(descriptor)


def _source(request: EntrypointRequest, parent: int) -> CapturedFile:
    if request.source.name != request.target.name:
        raise ValueError("source and target must name the same existing file")
    if request.supporting_document:
        if request.source.suffix != ".md" or request.source.name == "SKILL.md":
            raise ValueError("supporting-document maintenance accepts only sibling Markdown documents")
    elif request.source.name != "SKILL.md":
        raise ValueError("maintenance accepts only existing SKILL.md entrypoints")
    captured = _capture(parent, request.source.name)
    if captured.digest != request.expected_source:
        raise ValueError("source digest differs from the selected candidate")
    try:
        entrypoint = _capture(parent, "SKILL.md") if request.supporting_document else captured
        metadata, _body, closed = read_frontmatter(entrypoint.data.decode("utf-8"))
    except (UnicodeError, YAMLError) as exc:
        raise ValueError("source entrypoint metadata is malformed") from exc
    name, description = metadata.get("name"), metadata.get("description")
    if not closed or not isinstance(name, str) or name != request.target.parent.name:
        raise ValueError("source must declare the existing target skill name")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("source must contain a non-empty description")
    return captured


def check_entrypoint(request: EntrypointRequest) -> str:
    """Return matching or repairable; reject unexpected state without writing."""
    request = EntrypointRequest.model_validate(dict(request))
    source_parent = _open_directory_tree(request.source.parent)
    try:
        source = _source(request, source_parent)
        target_parent = _open_directory_tree(request.target.parent)
        try:
            current = _capture(target_parent, request.target.name)
            if current.digest == source.digest:
                return "matching"
            if current.digest != request.expected_current:
                raise ValueError("runtime digest differs from the approved repair input")
            return "repairable"
        finally:
            os.close(target_parent)
    finally:
        os.close(source_parent)


def _write_stage(parent: int, name: str, source: CapturedFile, current: CapturedFile) -> int:
    mode = stat.S_IMODE(current.mode)
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
    try:
        with os.fdopen(os.dup(descriptor), "wb") as stream:
            stream.write(source.data)
            stream.flush()
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        return descriptor
    except (OSError, ValueError):
        try:
            _remove_owned(parent, name, descriptor)
        finally:
            os.close(descriptor)
        raise


def _remove_owned(parent: int, name: str, descriptor: int) -> None:
    try:
        observed = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    owned = os.fstat(descriptor)
    if (observed.st_dev, observed.st_ino) != (owned.st_dev, owned.st_ino):
        raise ValueError("operation-owned path was replaced; refusing cleanup")
    os.unlink(name, dir_fd=parent)


def _verify_parents(request: EntrypointRequest, parents: tuple[int, int, int]) -> None:
    for path, original in zip(
        (request.source.parent, request.target.parent, request.backup_root), parents, strict=True
    ):
        reopened = _open_directory_tree(path)
        try:
            current, expected = os.fstat(reopened), os.fstat(original)
            if (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino):
                raise ValueError("source, runtime, or backup directory was replaced")
        finally:
            os.close(reopened)


def _publish(request: EntrypointRequest, parents: tuple[int, int, int], source: CapturedFile) -> str:
    source_parent, target_parent, backup_parent = parents
    current = _capture(target_parent, request.target.name)
    if current.digest == source.digest:
        _verify_parents(request, parents)
        return "matching"
    if current.digest != request.expected_current:
        raise ValueError("runtime changed before repair")
    operation = uuid.uuid4().hex
    stage_name = f".skills-sdk-stage-{operation}"
    backup_name = f"{request.target.parent.name}-{operation}-{request.target.name}"
    stage = _write_stage(target_parent, stage_name, source, current)
    try:
        os.link(
            request.target.name, backup_name, src_dir_fd=target_parent, dst_dir_fd=backup_parent, follow_symlinks=False
        )
        os.fsync(backup_parent)
        backup = _capture(backup_parent, backup_name)
        latest = _capture(target_parent, request.target.name)
        if backup != current or latest != current or _source(request, source_parent) != source:
            raise ValueError("source or runtime changed before publication; backup retained")
        _verify_parents(request, parents)
        os.replace(stage_name, request.target.name, src_dir_fd=target_parent, dst_dir_fd=target_parent)
        os.fsync(target_parent)
        _verify_parents(request, parents)
        if (
            _capture(target_parent, request.target.name).digest != source.digest
            or _capture(backup_parent, backup_name) != current
        ):
            raise ValueError("concurrent runtime mutation detected; result indeterminate and backup retained")
        return f"repaired; backup={backup_name}"
    finally:
        try:
            _remove_owned(target_parent, stage_name, stage)
        finally:
            os.close(stage)


def repair_entrypoint(request: EntrypointRequest) -> str:
    """Apply one explicitly authorized repair with a retained hard-link backup.

    Callers must separately establish user authority and a quiescent target.
    A cooperative lock and observed race checks do not defeat privileged writers.
    """
    request = EntrypointRequest.model_validate(dict(request))
    parents: list[int] = []
    try:
        for path in (request.source.parent, request.target.parent, request.backup_root):
            parents.append(_open_directory_tree(path))
        source_parent, target_parent, backup_parent = parents
        source = _source(request, source_parent)
        lock_name = ".skills-sdk-entrypoint.lock"
        lock = os.open(lock_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=target_parent)
        try:
            return _publish(request, (source_parent, target_parent, backup_parent), source)
        finally:
            try:
                _remove_owned(target_parent, lock_name, lock)
            finally:
                os.close(lock)
    finally:
        for descriptor in reversed(parents):
            os.close(descriptor)
