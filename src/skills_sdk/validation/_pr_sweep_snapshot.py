"""Bounded descriptor-relative copying for private PR-sweep snapshots."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SnapshotSkip = Callable[[Path, int], bool]


@dataclass(slots=True)
class SnapshotBudget:
    """Share byte, entry, and depth limits across every copied snapshot tree."""

    max_bytes: int
    max_entries: int
    max_depth: int
    copied_bytes: int = 0
    entries: int = 0

    def claim_entry(self, depth: int) -> None:
        """Charge one observed source object before creating its destination."""
        self.entries += 1
        if self.entries > self.max_entries or depth > self.max_depth:
            raise OSError("private snapshot exceeds its object budget")

    def claim_bytes(self, size: int) -> None:
        """Charge regular-file payload before writing it to the destination."""
        self.copied_bytes += size
        if self.copied_bytes > self.max_bytes:
            raise OSError("private snapshot exceeds its copy budget")


def _directory_flags() -> int:
    directory = getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not directory or not nofollow or os.open not in os.supports_dir_fd or os.scandir not in os.supports_fd:
        raise OSError("safe descriptor-relative snapshot traversal is unavailable")
    return os.O_RDONLY | directory | nofollow


def _entry_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode)


def _copy_metadata(destination_fd: int, source: os.stat_result) -> None:
    os.fchmod(destination_fd, stat.S_IMODE(source.st_mode))
    os.utime(destination_fd, ns=(source.st_atime_ns, source.st_mtime_ns))


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written == 0:
            raise OSError("private snapshot write did not progress")
        remaining = remaining[written:]


def _copy_regular_file(source_parent: int, destination_parent: int, name: str, budget: SnapshotBudget) -> None:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    source_fd = os.open(name, flags, dir_fd=source_parent)
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode):
            raise OSError("snapshot source changed type while copying")
        destination_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=destination_parent)
        try:
            while chunk := os.read(source_fd, 1024 * 1024):
                budget.claim_bytes(len(chunk))
                _write_all(destination_fd, chunk)
            after = os.fstat(source_fd)
            if _entry_identity(before) != _entry_identity(after) or (
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise OSError("snapshot source changed while copying")
            _copy_metadata(destination_fd, after)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)


def _copy_snapshot_entry(
    source_parent: int,
    destination_parent: int,
    relative: Path,
    budget: SnapshotBudget,
    should_skip: SnapshotSkip | None,
) -> None:
    name = relative.name
    source = os.stat(name, dir_fd=source_parent, follow_symlinks=False)
    budget.claim_entry(len(relative.parts))
    if should_skip is not None and should_skip(relative, source.st_mode):
        return
    if stat.S_ISLNK(source.st_mode):
        os.symlink(os.readlink(name, dir_fd=source_parent), name, dir_fd=destination_parent)
        return
    if stat.S_ISREG(source.st_mode):
        _copy_regular_file(source_parent, destination_parent, name, budget)
        return
    if not stat.S_ISDIR(source.st_mode):
        raise OSError("unsupported snapshot entry type")
    _copy_snapshot_subdirectory(source_parent, destination_parent, relative, budget, should_skip)


def _copy_snapshot_subdirectory(
    source_parent: int,
    destination_parent: int,
    relative: Path,
    budget: SnapshotBudget,
    should_skip: SnapshotSkip | None,
) -> None:
    flags = _directory_flags()
    source_fd = os.open(relative.name, flags, dir_fd=source_parent)
    try:
        os.mkdir(relative.name, mode=0o700, dir_fd=destination_parent)
        destination_fd = os.open(relative.name, flags, dir_fd=destination_parent)
        try:
            _copy_snapshot_directory(source_fd, destination_fd, relative, budget, should_skip)
            _copy_metadata(destination_fd, os.fstat(source_fd))
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)


def _copy_snapshot_directory(
    source_fd: int,
    destination_fd: int,
    relative: Path,
    budget: SnapshotBudget,
    should_skip: SnapshotSkip | None,
) -> None:
    with os.scandir(source_fd) as iterator:
        for entry in iterator:
            _copy_snapshot_entry(source_fd, destination_fd, relative / entry.name, budget, should_skip)


def copy_snapshot_tree(
    source: Path, destination: Path, budget: SnapshotBudget, *, should_skip: SnapshotSkip | None = None
) -> None:
    """Copy one tree without following links or materializing unbudgeted objects."""
    flags = _directory_flags()
    source_fd = os.open(source, flags)
    try:
        budget.claim_entry(0)
        destination.mkdir(mode=0o700)
        destination_fd = os.open(destination, flags)
        try:
            _copy_snapshot_directory(source_fd, destination_fd, Path(), budget, should_skip)
            _copy_metadata(destination_fd, os.fstat(source_fd))
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)
