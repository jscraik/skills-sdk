"""Bounded, candidate-manifest-bound reads for scorer evidence."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from skills_sdk.models.validation import SkillPackageValidation

_MAX_ARTIFACT_BYTES = 1_048_576


def read_candidate_artifact(root: Path, validation: SkillPackageValidation, relative_path: str) -> bytes:
    """Read a regular candidate file without following links or accepting changed bytes."""
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("invalid_artifact_path")
    manifest = next((item for item in validation.files if item.path == relative_path), None)
    if manifest is None:
        raise ValueError("artifact_not_in_candidate")
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    nofollow_flag = getattr(os, "O_NOFOLLOW", 0)
    if not directory_flag or not nofollow_flag or os.open not in os.supports_dir_fd:
        raise ValueError("safe_artifact_read_unavailable")
    descriptor = os.open(root, os.O_RDONLY | directory_flag | nofollow_flag)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | directory_flag | nofollow_flag, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(path.parts[-1], os.O_RDONLY | os.O_NONBLOCK | nofollow_flag, dir_fd=descriptor)
        try:
            before = os.fstat(file_descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_ARTIFACT_BYTES:
                raise ValueError("invalid_artifact_file")
            chunks: list[bytes] = []
            size = 0
            while size <= _MAX_ARTIFACT_BYTES:
                chunk = os.read(file_descriptor, min(65_536, _MAX_ARTIFACT_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            payload = b"".join(chunks)
            after = os.fstat(file_descriptor)
            if size > _MAX_ARTIFACT_BYTES or (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ino,
            ):
                raise ValueError("artifact_changed")
            if hashlib.sha256(payload).hexdigest() != manifest.sha256:
                raise ValueError("artifact_changed")
            return payload
        finally:
            os.close(file_descriptor)
    finally:
        os.close(descriptor)
