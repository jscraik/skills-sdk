"""Deterministic content digests for portable Skills SDK contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Protocol


class _ContentDigestFile(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def sha256(self) -> str: ...


def canonical_json_sha256(value: object) -> str:
    """Return the SHA-256 digest of one canonical JSON value."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def candidate_content_sha256(files: Iterable[_ContentDigestFile]) -> str:
    """Hash the ordered portable path and blob digest pairs for a candidate."""

    digest = hashlib.sha256()
    for item in files:
        digest.update(item.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


__all__ = ["candidate_content_sha256", "canonical_json_sha256"]
