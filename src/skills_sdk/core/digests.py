"""Deterministic content digests for portable Skills SDK contracts."""

from __future__ import annotations

import hashlib
import json


def canonical_json_sha256(value: object) -> str:
    """Return the SHA-256 digest of one canonical JSON value."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = ["canonical_json_sha256"]
