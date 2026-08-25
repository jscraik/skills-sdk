"""Candidate-bound receipt parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.core.schema_registry import SchemaRegistry


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    """Immutable package source and content identity."""

    package_id: str
    source_revision: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class Blocker:
    """A typed reason that a proof lane could not complete."""

    code: str
    message: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Receipt:
    """One validated proof-lane result bound to an immutable candidate."""

    receipt_id: str
    candidate: CandidateIdentity
    lane: str
    status: str
    evidence: tuple[str, ...]
    blocker: Blocker | None
    payload: Mapping[str, Any]

    def require_candidate(self, expected: CandidateIdentity) -> None:
        if self.candidate != expected:
            raise ContractError("candidate_mismatch", "receipt is bound to a different candidate")


def _parse_blocker(payload: Mapping[str, Any] | None) -> Blocker | None:
    if payload is None:
        return None
    refs = tuple(str(ref) for ref in payload["evidence_refs"])
    for ref in refs:
        require_portable_relative_path(ref)
    return Blocker(code=str(payload["code"]), message=str(payload["message"]), evidence_refs=refs)


def parse_receipt(payload: Mapping[str, Any], registry: SchemaRegistry | None = None) -> Receipt:
    """Validate untrusted receipt data and return immutable public records."""

    active_registry = registry or SchemaRegistry()
    active_registry.validate("receipt-base.v1", payload)
    candidate_payload = payload["candidate"]
    active_registry.validate("package-identity.v1", candidate_payload)
    evidence = tuple(str(ref) for ref in payload["evidence"])
    for ref in evidence:
        require_portable_relative_path(ref)
    blocker_payload = payload.get("blocker")
    if blocker_payload is not None:
        active_registry.validate("blocker.v1", blocker_payload)
    candidate = CandidateIdentity(
        package_id=str(candidate_payload["package_id"]),
        source_revision=str(candidate_payload["source_revision"]),
        content_sha256=str(candidate_payload["content_sha256"]),
    )
    return Receipt(
        receipt_id=str(payload["receipt_id"]),
        candidate=candidate,
        lane=str(payload["lane"]),
        status=str(payload["status"]),
        evidence=evidence,
        blocker=_parse_blocker(blocker_payload),
        payload=MappingProxyType(dict(payload)),
    )
