"""Portable path primitives shared by public contracts."""

from __future__ import annotations

from pathlib import PurePosixPath

from skills_sdk.core.errors import ContractError

_EXCLUDED_REFERENCE_TERMS = ("eval", "scorer", "rubric", "calibration", "heldout", "held-out", "hidden")


def require_portable_relative_path(value: str) -> PurePosixPath:
    """Return a normalized relative POSIX path or raise a typed error."""

    if not value or not value.strip() or "\\" in value or any(char in value for char in "\r\n"):
        raise ContractError("invalid_portable_path", "path must be a non-empty POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        raise ContractError("invalid_portable_path", "path must be relative and cannot escape its root")
    normalized = path.as_posix()
    if normalized != value or normalized in {".", ""}:
        raise ContractError("invalid_portable_path", "path must already be normalized")
    return path


def require_matched_reference_path(value: str, selected_skill_paths: tuple[str, ...]) -> PurePosixPath:
    """Keep matched plan and runtime reference selection under one portable rule."""
    path = require_portable_relative_path(value)
    if path.parts[0] == "skills" and "/".join(path.parts[:2]) not in selected_skill_paths:
        raise ValueError("matched references within skills must belong to a selected child")
    if path.suffix.casefold() not in {".md", ".markdown"} or any(
        term in part.casefold() for part in path.parts for term in _EXCLUDED_REFERENCE_TERMS
    ):
        raise ValueError("matched context excludes hidden evaluation inputs and non-Markdown references")
    if value in {f"{child}/SKILL.md" for child in selected_skill_paths}:
        raise ValueError("matched references must not duplicate automatic selected entrypoints")
    return path
