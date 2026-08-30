"""Portable candidate-bound package safety evidence contracts."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import BlockerCode, PackageReceiptV2, ReceiptId

SafetyEvidenceId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")]
SafetyAdapterId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[._/-][a-z0-9]+)*$")]
SafetyAdapterVersion = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")]
_CREDENTIAL_PREFIXES = ("aiza", "akia", "bearer", "ghp_", "github_pat_", "hf_", "sk-", "xoxb-", "xoxp-")
_MAX_SAFETY_INPUT_NESTING_DEPTH = 100
_RFC3339_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")
_PUBLIC_TEXT_CREDENTIAL_PATTERN = re.compile(
    rf"(?:^|[^A-Za-z0-9])(?:{'|'.join(re.escape(prefix) for prefix in _CREDENTIAL_PREFIXES)}|"
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----|"
    r"(?:(?:ssh_)?private[_-]?key|api[_-]?key|credential|password|secret|token)"
    r"(?:[_-][A-Za-z0-9]+)*"
    r"[\"']?[\s\u001c-\u001f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*[:=])",
    re.IGNORECASE | re.ASCII,
)
_MACHINE_PATH_PATTERN = re.compile(
    r"(?:[fF][iI][lL][eE]:)/+|(?:^|[^A-Za-z0-9])\\|(?:^|[^A-Za-z0-9/])/(?!/)|"
    r"(?:^|[^A-Za-z0-9/])/(?:[Uu][sS][eE][rR][sS]|[Hh][oO][mM][eE]|[Pp][rR][iI][vV][aA][tT][eE]|"
    r"[Tt][mM][pP]|[Ww][oO][rR][kK][sS][pP][aA][cC][eE]|[Vv][aA][rR]/[Ff][oO][lL][dD][eE][rR][sS]|"
    r"[Rr][Oo][Oo][Tt])/|"
    r"(?:^|[^A-Za-z0-9.:/])(?:[A-Za-z0-9._-]+/)+(?:[Uu][sS][eE][rR][sS]|[Hh][oO][mM][eE]|"
    r"[Pp][rR][iI][vV][aA][tT][eE]|[Tt][mM][pP]|[Ww][oO][rR][kK][sS][pP][aA][cC][eE]|"
    r"[Vv][aA][rR]/[Ff][oO][lL][dD][eE][rR][sS]|[Rr][Oo][Oo][Tt])/|"
    r"(?:^|[^A-Za-z0-9])[A-Za-z]:"
)


def _public_text_is_redaction_safe(value: str) -> bool:
    return _PUBLIC_TEXT_CREDENTIAL_PATTERN.search(value) is None and _MACHINE_PATH_PATTERN.search(value) is None


def _contains_byte_string(
    value: object,
    active_container_ids: set[int] | None = None,
    depth: int = 0,
) -> bool:
    if depth > _MAX_SAFETY_INPUT_NESTING_DEPTH:
        raise ValueError("safety public fields exceed the maximum JSON nesting depth")
    if isinstance(value, (bytes, bytearray)):
        return True
    if isinstance(value, str):
        return False
    if isinstance(value, BaseModel):
        return _contains_byte_string(value.model_dump(mode="python"), active_container_ids, depth + 1)
    if isinstance(value, Mapping | Sequence):
        active_container_ids = active_container_ids if active_container_ids is not None else set()
        container_id = id(value)
        if container_id in active_container_ids:
            raise ValueError("safety public fields must not contain cyclic containers")
        active_container_ids.add(container_id)
        try:
            values = value.values() if isinstance(value, Mapping) else value
            return any(_contains_byte_string(item, active_container_ids, depth + 1) for item in values)
        finally:
            active_container_ids.remove(container_id)
    if isinstance(value, Iterable):
        raise ValueError("safety public fields must use JSON-compatible containers")
    return False


class _SafetyContractModel(_ContractModel):
    @model_validator(mode="before")
    @classmethod
    def byte_strings_must_not_be_coerced(cls, value: object) -> object:
        if _contains_byte_string(value):
            raise ValueError("safety public fields must not coerce byte strings")
        return value


class PackageSafetyReviewer(_SafetyContractModel):
    """Secret-free identity for the caller-supplied review adapter."""

    adapter_id: SafetyAdapterId
    adapter_version_or_digest: SafetyAdapterVersion
    method: Literal["metadata", "static_analysis", "manual_review", "external_review"]

    @field_validator("adapter_id", "adapter_version_or_digest", mode="before")
    @classmethod
    def public_text_must_be_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str):
            if value != value.strip():
                raise ValueError("safety reviewer identity must already be normalized")
            if not _public_text_is_redaction_safe(value):
                raise ValueError("safety reviewer identity must not contain credential-shaped values")
        return value


class PackageSafetyEvidenceReference(_SafetyContractModel):
    """One digest-bound portable evidence artifact supplied by an adapter."""

    evidence_id: SafetyEvidenceId
    kind: Literal["metadata", "static_analysis", "manual_review", "external_review", "policy"]
    ref: PortablePath
    sha256: Sha256

    @field_validator("evidence_id", mode="before")
    @classmethod
    def evidence_id_must_be_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str):
            if value != value.strip():
                raise ValueError("safety evidence id must already be normalized")
            if not _public_text_is_redaction_safe(value):
                raise ValueError("safety evidence id must not contain credential-shaped values")
        return value

    @field_validator("ref")
    @classmethod
    def evidence_ref_must_be_portable_and_safe(cls, value: str) -> str:
        require_portable_relative_path(value)
        if not _public_text_is_redaction_safe(value):
            raise ValueError("safety evidence ref must not contain credential-shaped values")
        return value


class PackageSafetyFinding(_SafetyContractModel):
    """Redacted safety finding metadata linked to supplied evidence."""

    code: BlockerCode
    category: Literal[
        "secret",
        "private_data",
        "unsafe_operation",
        "unsafe_path",
        "dependency",
        "license",
        "other",
    ]
    severity: Literal["info", "warning", "blocker"]
    message: NonEmptyText
    evidence_ids: tuple[SafetyEvidenceId, ...] = Field(min_length=1)

    @field_validator("code", "message", mode="before")
    @classmethod
    def public_text_must_be_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str) and not _public_text_is_redaction_safe(value):
            raise ValueError("safety finding text must not contain credential-shaped values")
        return value

    @field_validator("code", mode="before")
    @classmethod
    def code_must_be_normalized(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("safety finding code must already be normalized")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_must_be_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("safety finding evidence ids must be unique")
        return values

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def evidence_ids_must_be_redaction_safe(cls, values: object) -> object:
        if isinstance(values, Iterable) and not isinstance(values, (str, bytes, bytearray, Mapping)):
            materialized = tuple(values)
            for value in materialized:
                if isinstance(value, str):
                    if value != value.strip():
                        raise ValueError("safety finding evidence ids must already be normalized")
                    if not _public_text_is_redaction_safe(value):
                        raise ValueError("safety finding evidence ids must not contain credential-shaped values")
            return materialized
        return values


class PackageSafetyBlocker(_SafetyContractModel):
    """Typed reason that a safety-review state cannot establish no issue."""

    code: BlockerCode
    message: NonEmptyText
    evidence_refs: tuple[PortablePath, ...] = ()

    @field_validator("code", "message", mode="before")
    @classmethod
    def public_text_must_be_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str) and not _public_text_is_redaction_safe(value):
            raise ValueError("safety blocker text must not contain credential-shaped values")
        return value

    @field_validator("code", mode="before")
    @classmethod
    def code_must_be_normalized(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("safety blocker code must already be normalized")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_unique_portable_and_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("safety blocker evidence refs must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not _public_text_is_redaction_safe(value):
                raise ValueError("safety blocker evidence must not contain credential-shaped values")
        return values


class PackageSafetyEvidenceReceipt(_SafetyContractModel):
    """One adapter-supplied package safety evidence state, never a safe boolean."""

    schema_version: Literal["package-safety-evidence/v1"]
    receipt_id: ReceiptId
    candidate: PackageCandidateIdentity
    lane: Literal["safety_review"]
    input_receipt_id: ReceiptId
    package_digest: Sha256
    reviewer: PackageSafetyReviewer
    status: Literal["not_reviewed", "reviewed_no_issue", "issue_found", "metadata_insufficient"]
    observed_at: AwareDatetime
    evidence: tuple[PackageSafetyEvidenceReference, ...] = ()
    findings: tuple[PackageSafetyFinding, ...] = ()
    blocker: PackageSafetyBlocker | None = None
    blockers: tuple[PackageSafetyBlocker, ...] = ()
    mutation_performed: Literal[False] = False
    rights_decision_performed: Literal[False] = False
    admission_performed: Literal[False] = False

    @field_validator("receipt_id", "input_receipt_id", mode="before")
    @classmethod
    def receipt_ids_must_be_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str):
            if value != value.strip():
                raise ValueError("safety receipt identity must already be normalized")
            if not _public_text_is_redaction_safe(value):
                raise ValueError("safety receipt identity must not contain credential-shaped values")
        return value

    @field_validator("observed_at", mode="before")
    @classmethod
    def observed_at_must_be_a_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("safety observed_at must be an RFC3339 string")
        if _RFC3339_DATETIME_PATTERN.fullmatch(value) is None:
            raise ValueError("safety observed_at must be an RFC3339 string")
        return value

    @model_validator(mode="after")
    def state_matches_evidence(self) -> PackageSafetyEvidenceReceipt:
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("safety evidence ids must be unique")
        evidence_refs = tuple(item.ref for item in self.evidence)
        if len(evidence_refs) != len(set(evidence_refs)):
            raise ValueError("safety evidence refs must be unique")
        finding_codes = tuple(item.code for item in self.findings)
        if len(finding_codes) != len(set(finding_codes)):
            raise ValueError("safety finding codes must be unique")
        if len(self.blockers) != len(set(self.blockers)):
            raise ValueError("safety blockers must be unique")
        known_ids = set(evidence_ids)
        known_refs = {item.ref for item in self.evidence}
        if any(not set(finding.evidence_ids) <= known_ids for finding in self.findings):
            raise ValueError("safety findings must reference supplied evidence ids")
        if any(not set(blocker.evidence_refs) <= known_refs for blocker in self.blockers):
            raise ValueError("safety blockers must reference supplied digest-bound evidence")
        if self.status == "not_reviewed":
            if self.evidence or self.findings or self.blocker is not None or self.blockers:
                raise ValueError("not_reviewed safety evidence cannot claim review artifacts")
        elif self.status == "reviewed_no_issue":
            if not self.evidence or self.findings or self.blocker is not None or self.blockers:
                raise ValueError("reviewed_no_issue requires evidence and no findings or blockers")
        elif self.status == "issue_found":
            if not self.evidence or not self.findings:
                raise ValueError("issue_found requires evidence and findings")
            if all(finding.severity == "info" for finding in self.findings):
                raise ValueError("issue_found requires a warning or blocker finding")
            if self.blocker is None or not self.blockers or self.blockers[0] != self.blocker:
                raise ValueError("issue_found requires its primary blocker first")
        else:
            if self.findings:
                raise ValueError("metadata_insufficient cannot claim an observed issue")
            if self.blocker is None or not self.blockers or self.blockers[0] != self.blocker:
                raise ValueError("metadata_insufficient requires its primary blocker first")
        return self

    def validate_against_package_receipt(self, package_receipt: PackageReceiptV2) -> PackageSafetyEvidenceReceipt:
        """Require this evidence receipt to bind one supplied built package receipt."""

        if not isinstance(package_receipt, PackageReceiptV2):
            raise ValueError("safety evidence requires a built v2 upstream package receipt")
        if (
            package_receipt.status != "built"
            or package_receipt.candidate is None
            or package_receipt.package_digest is None
        ):
            raise ValueError("safety evidence requires a built upstream package receipt")
        if self.input_receipt_id != package_receipt.receipt_id:
            raise ValueError("safety input receipt id must match the upstream package receipt")
        if self.candidate != package_receipt.candidate:
            raise ValueError("safety candidate must match the upstream package receipt")
        if self.package_digest != package_receipt.package_digest:
            raise ValueError("safety package digest must match the upstream package receipt")
        return self


__all__ = [
    "PackageSafetyBlocker",
    "PackageSafetyEvidenceReceipt",
    "PackageSafetyEvidenceReference",
    "PackageSafetyFinding",
    "PackageSafetyReviewer",
]
