"""Candidate-bound receipt parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.core.schema_registry import SchemaRegistry

_RECEIPT_SCHEMAS = {
    "receipt-base/v1": "receipt-base.v1",
    "package-receipt/v1": "package-receipt.v1",
    "package-receipt/v2": "package-receipt.v2",
    "evaluation-receipt/v1": "evaluation-receipt.v1",
    "evaluation-receipt/v2": "evaluation-receipt.v2",
}
_PACKAGE_RECEIPT_VERSIONS = frozenset({"package-receipt/v1", "package-receipt/v2"})
_EVALUATION_RECEIPT_VERSIONS = frozenset({"evaluation-receipt/v1", "evaluation-receipt/v2"})


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
    """One validated proof-lane result, candidate-bound when identity resolved."""

    receipt_id: str
    candidate: CandidateIdentity | None
    lane: str
    status: str
    evidence: tuple[str, ...]
    blocker: Blocker | None
    payload: Mapping[str, Any]
    artifact_status: str | None = None

    def require_candidate(self, expected: CandidateIdentity) -> None:
        if self.candidate is None:
            raise ContractError("candidate_unavailable", "receipt has no resolved candidate identity")
        if self.candidate != expected:
            raise ContractError("candidate_mismatch", "receipt is bound to a different candidate")


def _freeze_payload(value: Any) -> Any:
    """Copy JSON-shaped receipt data into recursively immutable containers."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_payload(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_payload(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_payload(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_payload(item) for item in value)
    return value


def _parse_blocker(payload: Mapping[str, Any] | None) -> Blocker | None:
    if payload is None:
        return None
    refs = tuple(str(ref) for ref in payload.get("evidence_refs", ()))
    for ref in refs:
        require_portable_relative_path(ref)
    return Blocker(code=str(payload["code"]), message=str(payload["message"]), evidence_refs=refs)


def parse_receipt(payload: Mapping[str, Any], registry: SchemaRegistry | None = None) -> Receipt:
    """Validate untrusted receipt data and return immutable public records."""

    active_registry = registry or SchemaRegistry()
    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str):
        raise ContractError(
            "invalid_receipt_schema_version",
            "receipt schema_version must be a registered string",
        )
    receipt_schema = _RECEIPT_SCHEMAS.get(schema_version)
    if receipt_schema is None:
        raise ContractError(
            "unsupported_receipt_family",
            "receipt schema_version is not registered",
        )
    package_receipt = schema_version in _PACKAGE_RECEIPT_VERSIONS
    evaluation_receipt = schema_version in _EVALUATION_RECEIPT_VERSIONS
    # Concrete receipt families validate their richer invariants before the
    # stable generic Receipt API is exposed to callers.
    active_registry.validate(receipt_schema, payload)
    candidate_payload = payload.get("candidate")
    if not package_receipt and not evaluation_receipt:
        active_registry.validate("package-identity.v1", candidate_payload)
    raw_evidence = payload.get("evidence", ())
    if evaluation_receipt:
        raw_evidence = tuple(
            ref
            for result in payload.get("case_results", ())
            if isinstance(result, Mapping)
            for ref in result.get("evidence_refs", ())
        )
    evidence = tuple(str(ref) for ref in raw_evidence)
    for ref in evidence:
        require_portable_relative_path(ref)
    blocker_payload = payload.get("blocker")
    if blocker_payload is not None and not package_receipt and not evaluation_receipt:
        active_registry.validate("blocker.v1", blocker_payload)
    candidate = (
        CandidateIdentity(
            package_id=str(candidate_payload["package_id"]),
            source_revision=str(candidate_payload["source_revision"]),
            content_sha256=str(candidate_payload["content_sha256"]),
        )
        if isinstance(candidate_payload, Mapping)
        else None
    )
    if package_receipt:
        artifact_status = str(payload["status"])
        generic_status = {
            "built": "pass",
            "blocked": "blocked",
        }.get(artifact_status, str(payload["status"]))
    else:
        artifact_status = None
        generic_status = str(payload["status"])
    return Receipt(
        receipt_id=str(payload["receipt_id"]),
        candidate=candidate,
        lane=str(payload["lane"]),
        status=generic_status,
        artifact_status=artifact_status,
        evidence=evidence,
        blocker=_parse_blocker(blocker_payload),
        payload=_freeze_payload(payload),
    )
