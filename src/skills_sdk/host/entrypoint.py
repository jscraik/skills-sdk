"""Digest-bound maintenance of an existing host SKILL.md, never package install."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import os
import platform
import stat
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from yaml import YAMLError

from skills_sdk.models.maintenance import EntrypointMaintenanceBlocker, EntrypointMaintenanceResult
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
    """Capture a bounded regular file without following symbolic links."""
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


def _validated_entrypoint(parent: int, expected_name: str) -> CapturedFile:
    captured = _capture(parent, "SKILL.md")
    try:
        metadata, _body, closed = read_frontmatter(captured.data.decode("utf-8"))
    except (RecursionError, UnicodeError, YAMLError) as exc:
        raise ValueError("entrypoint metadata is malformed") from exc
    description = metadata.get("description")
    if not closed or metadata.get("name") != expected_name:
        raise ValueError("entrypoint must declare the existing target skill name")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("entrypoint must contain a non-empty description")
    return captured


def _source(request: EntrypointRequest, parent: int, target_parent: int) -> CapturedFile:
    """Capture and validate the selected maintained source file."""
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
    if request.supporting_document:
        if captured.mode & 0o111:
            raise ValueError("supporting documents must not be executable")
        try:
            text = captured.data.decode("utf-8")
        except UnicodeError as exc:
            raise ValueError("supporting documents must be valid UTF-8 text") from exc
        if "\x00" in text:
            raise ValueError("supporting documents must be valid UTF-8 text")
        _validated_entrypoint(parent, request.target.parent.name)
        _validated_entrypoint(target_parent, request.target.parent.name)
    else:
        _validated_entrypoint(parent, request.target.parent.name)
    return captured


def check_entrypoint(request: EntrypointRequest) -> EntrypointMaintenanceResult:
    """Return matching or repairable; reject unexpected state without writing."""
    request = EntrypointRequest.model_validate(dict(request))
    _validate_backup_root(request)
    source_parent = _open_directory_tree(request.source.parent)
    try:
        target_parent = _open_directory_tree(request.target.parent)
        try:
            source = _source(request, source_parent, target_parent)
            current = _capture(target_parent, request.target.name)
            if request.supporting_document and current.mode & 0o111:
                raise ValueError("supporting documents must not be executable")
            if current.digest == source.digest:
                return EntrypointMaintenanceResult(status="matching")
            if current.digest != request.expected_current:
                raise ValueError("runtime digest differs from the approved repair input")
            return EntrypointMaintenanceResult(status="repairable")
        finally:
            os.close(target_parent)
    finally:
        os.close(source_parent)


def _write_stage(parent: int, name: str, source: CapturedFile, current: CapturedFile) -> int:
    """Write and sync an exclusive staged replacement with the current mode."""
    mode = stat.S_IMODE(current.mode) & 0o777
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
    """Remove a path only when it still names the operation-owned inode."""
    try:
        observed = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    owned = os.fstat(descriptor)
    if (observed.st_dev, observed.st_ino) != (owned.st_dev, owned.st_ino):
        raise ValueError("operation-owned path was replaced; refusing cleanup")
    os.unlink(name, dir_fd=parent)


def _write_snapshot(parent: int, name: str, captured: CapturedFile) -> None:
    descriptor = _write_stage(parent, name, captured, captured)
    os.close(descriptor)
    os.fsync(parent)


def _same_snapshot(left: CapturedFile, right: CapturedFile) -> bool:
    return (
        left.data == right.data
        and left.digest == right.digest
        and stat.S_IMODE(left.mode) == (stat.S_IMODE(right.mode) & 0o777)
    )


def _same_published(published: CapturedFile, source: CapturedFile, current: CapturedFile) -> bool:
    """Confirm published bytes and the sanitized original target mode."""
    return (
        published.data == source.data
        and published.digest == source.digest
        and stat.S_IMODE(published.mode) == (stat.S_IMODE(current.mode) & 0o777)
    )


def _exchange(parent: int, left: str, right: str) -> None:
    """Atomically exchange two names or fail closed before publication."""
    libc = ctypes.CDLL(None, use_errno=True)
    system = platform.system()
    function_name = "renameatx_np" if system == "Darwin" else "renameat2" if system == "Linux" else ""
    function = getattr(libc, function_name, None) if function_name else None
    if function is None:
        raise OSError(errno.ENOTSUP, "atomic path exchange is unavailable")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(parent, os.fsencode(left), parent, os.fsencode(right), 0x00000002) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _validate_backup_root(request: EntrypointRequest) -> None:
    backup = request.backup_root.resolve(strict=True)
    for package_root in (request.source.parent.resolve(strict=True), request.target.parent.resolve(strict=True)):
        if backup == package_root or backup.is_relative_to(package_root):
            raise ValueError("backup root must be outside source and runtime package trees")


def _verify_parents(request: EntrypointRequest, parents: tuple[int, int, int]) -> None:
    """Verify that each request directory still has its captured identity."""
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


def _publish(
    request: EntrypointRequest, parents: tuple[int, int, int], source: CapturedFile
) -> EntrypointMaintenanceResult:
    """Publish a staged replacement after backup and concurrency checks."""
    source_parent, target_parent, backup_parent = parents
    if os.fstat(target_parent).st_dev != os.fstat(backup_parent).st_dev:
        raise ValueError("backup root must be on the runtime target filesystem")
    current = _capture(target_parent, request.target.name)
    if request.supporting_document and current.mode & 0o111:
        raise ValueError("supporting documents must not be executable")
    if current.digest == source.digest:
        _verify_parents(request, parents)
        return EntrypointMaintenanceResult(status="matching")
    if current.digest != request.expected_current:
        raise ValueError("runtime changed before repair")
    operation = uuid.uuid4().hex
    stage_name = f".skills-sdk-stage-{operation}"
    target_key = hashlib.sha256(os.fsencode(request.target)).hexdigest()[:16]
    backup_name = f"entrypoint-{target_key}-{operation}.bak"
    recovery_name = f"entrypoint-{target_key}-{operation}.recovery"
    stage = _write_stage(target_parent, stage_name, source, current)
    retain_stage = False
    try:
        _write_snapshot(backup_parent, backup_name, current)
        backup = _capture(backup_parent, backup_name)
        latest = _capture(target_parent, request.target.name)
        if (
            not _same_snapshot(backup, current)
            or latest != current
            or _source(request, source_parent, target_parent) != source
        ):
            raise ValueError("source or runtime changed before publication; backup retained")
        _verify_parents(request, parents)
        try:
            _exchange(target_parent, stage_name, request.target.name)
        except OSError:
            return EntrypointMaintenanceResult(
                status="blocked",
                blocker=EntrypointMaintenanceBlocker(
                    code="publication_unavailable",
                    message="atomic publication was unavailable; snapshot retained",
                ),
                backup_name=backup_name,
            )
        try:
            os.fsync(target_parent)
            _verify_parents(request, parents)
            displaced = _capture(target_parent, stage_name)
            if displaced != current:
                retain_stage = True
                return EntrypointMaintenanceResult(
                    status="indeterminate",
                    blocker=EntrypointMaintenanceBlocker(
                        code="concurrent_runtime_replacement",
                        message="runtime changed at publication; competing bytes retained",
                    ),
                    backup_name=backup_name,
                    recovery_name=stage_name,
                )
            published = _capture(target_parent, request.target.name)
            if not _same_published(published, source, current) or not _same_snapshot(
                _capture(backup_parent, backup_name), current
            ):
                raise ValueError("published target or backup changed after publication")
        except (OSError, ValueError):
            retain_stage = True
            return EntrypointMaintenanceResult(
                status="indeterminate",
                blocker=EntrypointMaintenanceBlocker(
                    code="publication_verification_failed",
                    message="publication occurred but durable verification did not complete",
                ),
                backup_name=backup_name,
                recovery_name=stage_name,
            )
        moved_to_backup = False
        try:
            os.rename(stage_name, recovery_name, src_dir_fd=target_parent, dst_dir_fd=backup_parent)
            moved_to_backup = True
            recovery = _capture(backup_parent, recovery_name)
            if displaced != recovery:
                retain_stage = True
                return EntrypointMaintenanceResult(
                    status="indeterminate",
                    blocker=EntrypointMaintenanceBlocker(
                        code="concurrent_runtime_replacement",
                        message="runtime changed during recovery preservation",
                    ),
                    backup_name=backup_name,
                    recovery_name=recovery_name,
                )
        except (OSError, ValueError):
            retain_stage = True
            return EntrypointMaintenanceResult(
                status="indeterminate",
                blocker=EntrypointMaintenanceBlocker(
                    code="publication_verification_failed",
                    message="publication occurred but displaced bytes could not be preserved externally",
                ),
                backup_name=backup_name,
                recovery_name=recovery_name if moved_to_backup else stage_name,
            )
        return EntrypointMaintenanceResult(status="repaired", backup_name=backup_name)
    finally:
        if not retain_stage:
            with suppress(ValueError):
                _remove_owned(target_parent, stage_name, stage)
        os.close(stage)


def repair_entrypoint(request: EntrypointRequest) -> EntrypointMaintenanceResult:
    """Apply one explicitly authorized repair with an independent snapshot backup.

    Callers must separately establish user authority and a quiescent target.
    A cooperative lock and observed race checks do not defeat privileged writers.
    """
    request = EntrypointRequest.model_validate(dict(request))
    _validate_backup_root(request)
    parents: list[int] = []
    try:
        for path in (request.source.parent, request.target.parent, request.backup_root):
            parents.append(_open_directory_tree(path))
        source_parent, target_parent, backup_parent = parents
        source = _source(request, source_parent, target_parent)
        lock_key = hashlib.sha256(os.fsencode(request.target)).hexdigest()[:32]
        lock_name = f".skills-sdk-entrypoint-{lock_key}.lock"
        lock = os.open(
            lock_name,
            os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW,
            0o600,
            dir_fd=backup_parent,
        )
        try:
            if not stat.S_ISREG(os.fstat(lock).st_mode):
                raise ValueError("runtime lock must be a regular file")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another maintenance operation holds the runtime lock") from exc
            return _publish(request, (source_parent, target_parent, backup_parent), source)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)
    finally:
        for descriptor in reversed(parents):
            os.close(descriptor)
