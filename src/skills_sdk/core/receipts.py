"""Candidate-bound receipt parsing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.core.schema_registry import SchemaRegistry

_RECEIPT_SCHEMAS = {
    "receipt-base/v1": "receipt-base.v1",
    "package-receipt/v1": "package-receipt.v1",
    "package-receipt/v2": "package-receipt.v2",
    "evaluation-receipt/v1": "evaluation-receipt.v1",
    "evaluation-receipt/v2": "evaluation-receipt.v2",
    "registry-preparation/v1": "registry-preparation.v1",
    "package-safety-evidence/v1": "package-safety-evidence.v1",
    "installation-result/v1": "installation-result.v1",
    "rollback-outcome/v1": "rollback-outcome.v1",
    "discovery-observation/v1": "discovery-observation.v1",
    "activation-observation/v1": "activation-observation.v1",
    "runtime-outcome/v1": "runtime-outcome.v1",
    "plugin-build/v1": "plugin-build.v1",
    "plugin-hardening/v1": "plugin-hardening.v1",
}
_PACKAGE_RECEIPT_VERSIONS = frozenset({"package-receipt/v1", "package-receipt/v2"})
_EVALUATION_RECEIPT_VERSIONS = frozenset({"evaluation-receipt/v1", "evaluation-receipt/v2"})
_REGISTRY_RECEIPT_VERSIONS = frozenset({"registry-preparation/v1"})
_SAFETY_RECEIPT_VERSIONS = frozenset({"package-safety-evidence/v1"})
_RUNTIME_EVIDENCE_RECEIPT_VERSIONS = frozenset(
    {
        "installation-result/v1",
        "rollback-outcome/v1",
        "discovery-observation/v1",
        "activation-observation/v1",
        "runtime-outcome/v1",
    }
)


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
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        return tuple(_freeze_payload(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_payload(item) for item in value)
    return value


def _json_payload(value: Any) -> Any:
    """Restore validated immutable JSON containers before canonical hashing."""

    if isinstance(value, Mapping):
        return {key: _json_payload(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        return [_json_payload(item) for item in value]
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
    registry_receipt = schema_version in _REGISTRY_RECEIPT_VERSIONS
    safety_receipt = schema_version in _SAFETY_RECEIPT_VERSIONS
    runtime_evidence_receipt = schema_version in _RUNTIME_EVIDENCE_RECEIPT_VERSIONS
    # Concrete receipt families validate their richer invariants before the
    # stable generic Receipt API is exposed to callers.
    active_registry.validate(receipt_schema, payload)
    if schema_version in {"plugin-build/v1", "plugin-hardening/v1"}:
        return _parse_plugin_local_receipt(payload)
    candidate_payload = payload.get("candidate")
    known_candidate_receipt = any(
        (package_receipt, evaluation_receipt, registry_receipt, safety_receipt, runtime_evidence_receipt)
    )
    if not known_candidate_receipt:
        active_registry.validate("package-identity.v1", candidate_payload)
    raw_evidence = payload.get("evidence", ())
    if evaluation_receipt:
        raw_evidence = tuple(
            ref
            for result in payload.get("case_results", ())
            if isinstance(result, Mapping)
            for ref in result.get("evidence_refs", ())
        )
    elif safety_receipt:
        raw_evidence = tuple(str(item.get("ref")) for item in payload.get("evidence", ()) if isinstance(item, Mapping))
    evidence = tuple(str(ref) for ref in raw_evidence)
    for ref in evidence:
        require_portable_relative_path(ref)
    blocker_payload = payload.get("blocker")
    if safety_receipt and payload.get("status") == "not_reviewed":
        blocker_payload = {
            "code": "not_reviewed",
            "message": "package safety review was not performed",
            "evidence_refs": (),
        }
    if (
        blocker_payload is not None
        and not package_receipt
        and not evaluation_receipt
        and not registry_receipt
        and not safety_receipt
        and not runtime_evidence_receipt
    ):
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
    if package_receipt or registry_receipt or safety_receipt or runtime_evidence_receipt:
        artifact_status = str(payload["status"])
        generic_status = {
            "built": "pass",
            "prepared": "pass",
            "reviewed_no_issue": "pass",
            "not_reviewed": "blocked",
            "issue_found": "blocked",
            "metadata_insufficient": "blocked",
            "blocked": "blocked",
            "completed": "pass",
            "rolled_back": "blocked",
            "discovered": "pass",
            "active": "pass",
            "failed": "blocked",
            "rollback_failed": "blocked",
            "not_discovered": "blocked",
            "inactive": "blocked",
            "indeterminate": "blocked",
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


def _parse_plugin_local_receipt(payload: Mapping[str, Any]) -> Receipt:
    """Project validated local plugin families without inventing export or release evidence."""
    hardening = payload["schema_version"] == "plugin-hardening/v1"
    build = payload["build"] if hardening else payload
    capture = build["validation"]
    identity = capture.get("candidate")
    status = str(payload["status"])
    code = None
    if status == "blocked":
        code = (
            payload["blockers"][0]
            if hardening
            else next(
                (item["code"] for item in capture.get("findings", ()) if item["severity"] == "blocker"),
                "plugin_build_blocked",
            )
        )
    return Receipt(
        receipt_id="plugin-local-" + canonical_json_sha256(_json_payload(payload)),
        candidate=(
            CandidateIdentity(
                package_id=identity["package_id"],
                source_revision=identity["source_revision"],
                content_sha256=identity["content_sha256"],
            )
            if identity is not None
            else None
        ),
        lane="hardening" if hardening else "validation",
        status="blocked" if status == "blocked" else "pass",
        artifact_status=status,
        evidence=tuple(item["path"] for item in capture.get("files", ())),
        blocker=Blocker(code=code, message="Local whole-plugin operation blocked.", evidence_refs=()) if code else None,
        payload=_freeze_payload(payload),
    )
