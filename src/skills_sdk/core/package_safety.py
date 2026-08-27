"""Canonical package-path safety policy shared by validation and hardening."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Final

UNSAFE_PACKAGE_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".agents",
        ".cache",
        ".codex",
        ".git",
        ".gnupg",
        ".harness",
        ".mypy_cache",
        ".plugin-appserver",
        ".pytest_cache",
        ".ruff_cache",
        ".ssh",
        ".tox",
        ".venv",
        "__pycache__",
        "artifacts",
        "dist",
        "node_modules",
        "venv",
    }
)
UNSAFE_PACKAGE_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        ".env",
        ".netrc",
        ".npmrc",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
    }
)
UNSAFE_PACKAGE_SUFFIXES: Final[tuple[str, ...]] = (".key", ".p12", ".pem", ".pfx", ".token")


def unsafe_package_file_reason(name: str) -> str | None:
    """Return the canonical rejection reason for one package filename."""

    normalized = name.lower()
    if normalized in UNSAFE_PACKAGE_FILENAMES:
        return "forbidden_filename"
    if normalized.startswith(".env."):
        return "forbidden_env_family"
    if normalized == "skill-package-validation.json" or normalized.endswith("-receipt.json"):
        return "forbidden_generated_receipt"
    if normalized.endswith(UNSAFE_PACKAGE_SUFFIXES):
        return "forbidden_secret_suffix"
    return None


def unsafe_package_path_reason(path: str) -> str | None:
    """Return the canonical rejection reason for one portable package path."""

    parts = tuple(part.lower() for part in PurePosixPath(path).parts)
    if any(part in UNSAFE_PACKAGE_DIRECTORIES for part in parts):
        return "forbidden_path_part"
    return unsafe_package_file_reason(parts[-1])


__all__ = [
    "UNSAFE_PACKAGE_DIRECTORIES",
    "unsafe_package_file_reason",
    "unsafe_package_path_reason",
]
