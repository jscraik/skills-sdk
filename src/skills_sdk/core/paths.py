"""Portable path primitives shared by public contracts."""

from __future__ import annotations

from pathlib import PurePosixPath

from skills_sdk.core.errors import ContractError


def require_portable_relative_path(value: str) -> PurePosixPath:
    """Return a normalized relative POSIX path or raise a typed error."""

    if not value or "\\" in value or any(char in value for char in "\r\n"):
        raise ContractError("invalid_portable_path", "path must be a non-empty POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        raise ContractError("invalid_portable_path", "path must be relative and cannot escape its root")
    normalized = path.as_posix()
    if normalized != value or normalized in {".", ""}:
        raise ContractError("invalid_portable_path", "path must already be normalized")
    return path
