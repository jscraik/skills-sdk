"""Bounded whole-plugin capture, never executing package resources."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from skills_sdk.core.package_safety import UNSAFE_PACKAGE_DIRECTORIES, unsafe_package_file_reason
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.plugin import PluginCapturedFile
from skills_sdk.validation.skill_package import _open_directory_tree

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILES = 1024
MAX_RESOURCES = 2048
MAX_DEPTH = 64


def _metadata(descriptor: int) -> tuple[int, ...]:
    """Return descriptor identity, mode, size and timestamps for detecting capture drift."""
    value = os.fstat(descriptor)
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _read_file(parent: int, name: str) -> tuple[bytes, int]:
    """Read a bounded regular file without following links and return bytes and permissions."""
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = _metadata(descriptor)
        if not stat.S_ISREG(before[2]) or before[2] & 0o7000 or before[3] > MAX_FILE_BYTES:
            raise ValueError("plugin files require bounded ordinary regular-file bytes")
        chunks, remaining = [], before[3] + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if before != _metadata(descriptor) or len(payload) != before[3]:
            raise ValueError("plugin source changed during capture")
        return payload, stat.S_IMODE(before[2])
    finally:
        os.close(descriptor)


def capture_plugin_source(root: Path) -> tuple[tuple[PluginCapturedFile, ...], dict[str, bytes], tuple[str, ...]]:
    """Capture all resources using no-follow descriptors and bounded reads."""
    if not getattr(os, "O_NONBLOCK", 0):
        raise OSError("safe nonblocking package reads are unavailable")
    payloads: dict[str, bytes] = {}
    records: list[PluginCapturedFile] = []
    directories: list[str] = []
    resource_count, total_size = 0, 0

    def visit(descriptor: int, prefix: str, depth: int) -> None:
        """Collect files and directories recursively while enforcing budgets and detecting drift."""
        nonlocal resource_count, total_size
        before = _metadata(descriptor)
        if depth > MAX_DEPTH or before[2] & 0o7000:
            raise ValueError("plugin directory exceeds ordinary capture bounds")
        with os.scandir(descriptor) as iterator:
            names = []
            for entry in iterator:
                resource_count += 1
                if resource_count > MAX_RESOURCES:
                    raise ValueError("plugin resources exceed their bound")
                names.append(entry.name)
        for name in sorted(names):
            path = f"{prefix}/{name}" if prefix else name
            path.encode("utf-8")
            require_portable_relative_path(path)
            if name.lower() in UNSAFE_PACKAGE_DIRECTORIES or unsafe_package_file_reason(name) is not None:
                raise ValueError("unsafe plugin resource")
            value = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(value.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    directories.append(path)
                    visit(child, path, depth + 1)
                finally:
                    os.close(child)
            else:
                if len(records) >= MAX_FILES or total_size + value.st_size > MAX_TOTAL_BYTES:
                    raise ValueError("plugin capture exceeds its resource budget")
                payload, mode = _read_file(descriptor, name)
                total_size += len(payload)
                if total_size > MAX_TOTAL_BYTES:
                    raise ValueError("plugin bytes exceed their bound")
                payloads[path] = payload
                records.append(
                    PluginCapturedFile(
                        path=path,
                        sha256=hashlib.sha256(payload).hexdigest(),
                        size_bytes=len(payload),
                        permission_mode=mode,
                    )
                )
        if before != _metadata(descriptor):
            raise ValueError("plugin directory changed during capture")

    descriptor = _open_directory_tree(root)
    try:
        visit(descriptor, "", 0)
    finally:
        os.close(descriptor)
    return tuple(sorted(records, key=lambda item: item.path)), payloads, tuple(sorted(directories))
