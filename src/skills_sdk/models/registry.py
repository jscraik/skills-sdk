"""Portable private-registry preparation contracts."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PackageId, PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import ReceiptId

RegistryIdentifier = Annotated[
    str,
    StringConstraints(max_length=64, pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$"),
]
REGISTRY_PACKAGE_NAME_MAX_LENGTH = 64
_SEMVER_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
REGISTRY_VERSION_PATTERN = (
    rf"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    rf"(?:-{_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER})*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_REGISTRY_VERSION_PATTERN = re.compile(REGISTRY_VERSION_PATTERN)

_CREDENTIAL_PREFIXES = ("aiza", "akia", "bearer", "ghp_", "github_pat_", "hf_", "sk-", "xoxb-", "xoxp-")
_CREDENTIAL_COMPONENT_PATTERN = re.compile(
    rf"(?:^|[._-])(?:{'|'.join(re.escape(prefix) for prefix in _CREDENTIAL_PREFIXES)})",
    re.IGNORECASE,
)
_PUBLIC_TEXT_CREDENTIAL_PATTERN = re.compile(
    rf"(?:^|[^A-Za-z0-9])(?:{'|'.join(re.escape(prefix) for prefix in _CREDENTIAL_PREFIXES)})",
    re.IGNORECASE,
)


def registry_evidence_is_redaction_safe(value: str) -> bool:
    """Return whether text avoids the configured credential-prefix components."""

    return _PUBLIC_TEXT_CREDENTIAL_PATTERN.search(value) is None


class RegistryIdentity(_ContractModel):
    """Opaque, secret-free identity for one private registry namespace."""

    schema_version: Literal["registry-identity/v1"] = "registry-identity/v1"
    registry_id: RegistryIdentifier
    registry_kind: Literal["private"] = "private"
    namespace: RegistryIdentifier

    @field_validator("registry_id", "namespace", mode="before")
    @classmethod
    def identity_text_is_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str):
            if value != value.strip():
                raise ValueError("registry identity must not contain surrounding whitespace")
            if _CREDENTIAL_COMPONENT_PATTERN.search(value):
                raise ValueError("registry identity must not contain credential-shaped values")
        return value


class RegistryPreparationRequest(_ContractModel):
    """Secret-free caller intent for one local registry preparation."""

    schema_version: Literal["registry-preparation-request/v1"] = "registry-preparation-request/v1"
    registry: RegistryIdentity
    package_name: PackageId
    version: NonEmptyText
    evidence: tuple[PortablePath, ...] = Field(min_length=1)

    @field_validator("package_name", mode="before")
    @classmethod
    def package_name_is_redaction_safe(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("registry package name must be a string")
        if not registry_evidence_is_redaction_safe(value):
            raise ValueError("registry package name must not contain credential-shaped values")
        return value

    @field_validator("version", mode="before")
    @classmethod
    def version_is_canonical_text(cls, value: object) -> object:
        if isinstance(value, str):
            if value != value.strip():
                raise ValueError("registry version must not contain surrounding whitespace")
            if not registry_evidence_is_redaction_safe(value):
                raise ValueError("registry version must not contain credential-shaped values")
        return value

    @field_validator("evidence")
    @classmethod
    def evidence_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("registry preparation evidence paths must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not registry_evidence_is_redaction_safe(value):
                raise ValueError("registry preparation evidence must not contain credential-shaped values")
        return values


class RegistryPreparationBlocker(_ContractModel):
    """Registry-owned blocker retaining both path and non-path source evidence."""

    code: NonEmptyText
    message: NonEmptyText
    evidence_refs: tuple[PortablePath, ...] = ()
    source_evidence_sha256: tuple[Sha256, ...] = ()
    source_blocker_sha256: Sha256 | None = None

    @field_validator("code", "message", mode="before")
    @classmethod
    def public_text_is_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str) and not registry_evidence_is_redaction_safe(value):
            raise ValueError("registry blocker text must not contain credential-shaped values")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("registry blocker evidence references must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not registry_evidence_is_redaction_safe(value):
                raise ValueError("registry blocker evidence must not contain credential-shaped values")
        return values


class RegistryPreparationWarning(_ContractModel):
    """Secret-free digest projection of one hardening warning."""

    status: Literal["warning"] = "warning"
    warning_sha256: Sha256
    evidence_refs: tuple[PortablePath, ...] = ()
    source_evidence_sha256: tuple[Sha256, ...] = ()

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("registry warning evidence references must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not registry_evidence_is_redaction_safe(value):
                raise ValueError("registry warning evidence must not contain credential-shaped values")
        return values


class RegistryPreparationReceipt(_ContractModel):
    """Candidate-bound local preparation result that never publishes."""

    schema_version: Literal["registry-preparation/v1"] = "registry-preparation/v1"
    receipt_id: ReceiptId
    candidate: PackageCandidateIdentity | None = None
    lane: Literal["distribution"] = "distribution"
    registry: RegistryIdentity
    package_name: PackageId
    version: NonEmptyText
    input_receipt_id: ReceiptId
    package_digest: Sha256 | None = None
    manifest_digest: Sha256 | None = None
    hardening_receipt_sha256: Sha256 | None = None
    status: Literal["prepared", "blocked"]
    evidence: tuple[PortablePath, ...] = Field(min_length=1)
    blocker: RegistryPreparationBlocker | None = None
    blockers: tuple[RegistryPreparationBlocker, ...] = ()
    warnings: tuple[RegistryPreparationWarning, ...] = ()
    mutation_performed: Literal[False] = False
    publication_performed: Literal[False] = False

    @field_validator("package_name", mode="before")
    @classmethod
    def package_name_is_redaction_safe(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("registry package name must be a string")
        if not registry_evidence_is_redaction_safe(value):
            raise ValueError("registry package name must not contain credential-shaped values")
        return value

    @field_validator("version", mode="before")
    @classmethod
    def version_is_canonical_text(cls, value: object) -> object:
        if isinstance(value, str):
            if value != value.strip():
                raise ValueError("registry version must not contain surrounding whitespace")
            if not registry_evidence_is_redaction_safe(value):
                raise ValueError("registry version must not contain credential-shaped values")
        return value

    @field_validator("evidence")
    @classmethod
    def evidence_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("registry preparation evidence paths must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not registry_evidence_is_redaction_safe(value):
                raise ValueError("registry receipt evidence must not contain credential-shaped values")
        return values

    @model_validator(mode="after")
    def status_matches_artifacts(self) -> RegistryPreparationReceipt:
        digests = (self.package_digest, self.manifest_digest, self.hardening_receipt_sha256)
        if self.status == "prepared":
            if self.candidate is None or any(value is None for value in digests):
                raise ValueError("prepared registry receipt requires candidate and bound digests")
            if self.package_digest != self.manifest_digest:
                raise ValueError("prepared registry package and manifest digests must match")
            if self.package_name != self.candidate.package_id:
                raise ValueError("prepared registry package name must match the candidate package_id")
            if len(self.package_name) > REGISTRY_PACKAGE_NAME_MAX_LENGTH:
                raise ValueError("prepared registry package name exceeds the registry limit")
            if not _REGISTRY_VERSION_PATTERN.fullmatch(self.version):
                raise ValueError("prepared registry version must be canonical Semantic Versioning")
            if self.blocker is not None:
                raise ValueError("prepared registry receipt cannot contain a blocker")
            if self.blockers:
                raise ValueError("prepared registry receipt cannot contain blockers")
        else:
            if self.blocker is None:
                raise ValueError("blocked registry receipt requires a blocker")
            if not self.blockers or self.blockers[0] != self.blocker:
                raise ValueError("blocked registry receipt must retain its primary blocker first")
            if any(value is not None for value in digests):
                raise ValueError("blocked registry receipt cannot claim prepared digests")
        return self


__all__ = [
    "RegistryIdentity",
    "RegistryPreparationBlocker",
    "RegistryPreparationReceipt",
    "RegistryPreparationRequest",
    "RegistryPreparationWarning",
]
