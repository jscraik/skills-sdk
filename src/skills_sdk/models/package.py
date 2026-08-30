"""Portable package identity, source, ownership, and intake contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from skills_sdk.models.inventory import (
    GitRevision,
    NonEmptyText,
    PackageId,
    PackageType,
    RightsStatus,
    SourceProvenance,
    _ContractModel,
)

PackageName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
PluginName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")]


class PackageSourceKind(StrEnum):
    """How a package source was obtained before normalization."""

    GIT = "git"
    ARCHIVE = "archive"
    EXTERNAL = "external"
    LOCAL = "local"


class OwnershipState(StrEnum):
    """Ownership posture at intake; it is not a runtime state."""

    CANONICAL = "canonical"
    TRANSITIONAL = "transitional"
    EXTERNAL = "external"


class IntakeDecisionStatus(StrEnum):
    """Explicit intake result with no implicit waiver path."""

    ADMIT = "admit"
    BLOCK = "block"
    REJECT = "reject"
    NEEDS_OWNER_DECISION = "needs_owner_decision"


class PackageLifecycleState(StrEnum):
    """Portable lifecycle state for a normalized package candidate."""

    DISCOVERED = "discovered"
    NORMALIZED = "normalized"
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    RETIRED = "retired"


class PackageCandidateIdentity(_ContractModel):
    """Immutable identity shared by intake and downstream proof receipts."""

    schema_version: Literal["package-candidate/v1"] = "package-candidate/v1"
    package_id: PackageId
    source_revision: GitRevision
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("package_id", "source_revision", "content_sha256", mode="before")
    @classmethod
    def identity_fields_must_be_normalized(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("package candidate identity fields must already be normalized")
        return value


class SkillIdentity(_ContractModel):
    """Agent Skills identity, independent of runtime installation."""

    schema_version: Literal["skill-identity/v1"] = "skill-identity/v1"
    package_type: Literal["skill"] = "skill"
    package_id: PackageId
    name: PackageName
    version: NonEmptyText

    @model_validator(mode="after")
    def name_matches_package_id(self) -> SkillIdentity:
        if self.package_id != self.name:
            raise ValueError("skill package_id must match its kebab-case name")
        return self


class PluginIdentity(_ContractModel):
    """Agent Plugins identity, independent of a client adapter."""

    schema_version: Literal["plugin-identity/v1"] = "plugin-identity/v1"
    package_type: Literal["plugin"] = "plugin"
    package_id: PackageId
    name: PluginName
    version: NonEmptyText


class PackageSource(_ContractModel):
    """Source identity preserved before a package is normalized."""

    schema_version: Literal["package-source/v1"] = "package-source/v1"
    package_id: PackageId
    provenance: SourceProvenance
    source_kind: PackageSourceKind

    @field_validator("package_id")
    @classmethod
    def package_id_must_be_nonempty(cls, value: str) -> str:
        return value


class PackageOwner(_ContractModel):
    """Canonical ownership and rights evidence for one package candidate."""

    schema_version: Literal["package-owner/v1"] = "package-owner/v1"
    owner: NonEmptyText
    maintainer: NonEmptyText
    ownership_state: OwnershipState
    rights: RightsStatus


class IntakeChecks(_ContractModel):
    """Boolean proof lanes required before canonical admission."""

    identity: bool
    provenance: bool
    rights: bool
    owner_unchanged: bool


class IntakeDecision(_ContractModel):
    """Candidate-bound admission result with typed, explicit blockers."""

    schema_version: Literal["intake-decision/v1"] = "intake-decision/v1"
    candidate: PackageCandidateIdentity
    decision: IntakeDecisionStatus
    checks: IntakeChecks
    blocker_codes: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def enforce_decision_contract(self) -> IntakeDecision:
        checks_pass = all(self.checks.model_dump().values())
        if self.decision == IntakeDecisionStatus.ADMIT:
            if not checks_pass or self.blocker_codes:
                raise ValueError("admit requires all intake checks and no blockers")
        elif not self.blocker_codes:
            raise ValueError("non-admit decisions require at least one blocker code")
        return self


class NormalizedPackage(_ContractModel):
    """Portable normalized package before provider or runtime projection."""

    schema_version: Literal["normalized-package/v1"] = "normalized-package/v1"
    package_type: PackageType
    identity: Annotated[SkillIdentity | PluginIdentity, Field(discriminator="package_type")]
    source: PackageSource
    owner: PackageOwner
    lifecycle: PackageLifecycleState = PackageLifecycleState.NORMALIZED
    dependencies: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def identity_and_source_match(self) -> NormalizedPackage:
        if self.identity.package_type != self.package_type.value:
            raise ValueError("identity package_type must match normalized package_type")
        if self.identity.package_id != self.source.package_id:
            raise ValueError("identity and source package_id values must match")
        return self


__all__ = [
    "IntakeChecks",
    "IntakeDecision",
    "IntakeDecisionStatus",
    "NormalizedPackage",
    "OwnershipState",
    "PackageCandidateIdentity",
    "PackageLifecycleState",
    "PackageOwner",
    "PackageSource",
    "PackageSourceKind",
    "PluginIdentity",
    "SkillIdentity",
]
