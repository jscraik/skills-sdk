"""Portable package identity, source, ownership, and intake contracts."""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.inventory import (
    GitRevision,
    NonEmptyText,
    PackageId,
    PackageType,
    PortablePath,
    RightsStatus,
    SourceProvenance,
    _ContractModel,
)

PackageName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
PluginName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")]


def _candidate_package_id(directory_name: str, content_sha256: str) -> str:
    """Preserve the standalone candidate ID, including its invalid-name fallback."""
    if re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", directory_name):
        return directory_name
    root_digest = hashlib.sha256(directory_name.encode("utf-8", errors="surrogateescape")).hexdigest()[:6]
    return f"invalid-package-{root_digest}-{content_sha256[:12]}"


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

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["package-candidate/v1"] = "package-candidate/v1"
    package_id: PackageId
    source_revision: GitRevision
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


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


class SavedReleaseSnapshot(_ContractModel):
    """Supplied immutable release binding; neither origin authentication nor admission."""

    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["saved-release-snapshot/v1"] = "saved-release-snapshot/v1"
    locator: Annotated[str, StringConstraints(strip_whitespace=False, max_length=2048)]
    source_id: Annotated[str, StringConstraints(strip_whitespace=False, max_length=200)]
    release_id: Annotated[str, StringConstraints(strip_whitespace=False, max_length=200)]
    version: Annotated[str, StringConstraints(strip_whitespace=False, max_length=200)]
    archive_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    root_candidate: PackageCandidateIdentity
    root_mode_manifest_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    binding_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("archive_sha256", "root_mode_manifest_sha256", "binding_sha256", mode="before")
    @classmethod
    def digests_are_exact(cls, value: object) -> str:
        """Reject padding and coercion before shared text normalization."""
        if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("saved release digests require exact lowercase SHA-256")
        return value

    @field_validator("locator", mode="before")
    @classmethod
    def locator_is_public_https(cls, value: object) -> str:
        """Retain an exact bounded HTTPS locator without credentials, query or fragment."""
        pattern = r"https://[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?/[A-Za-z0-9._~/-]+"
        if type(value) is not str or re.fullmatch(pattern, value) is None:
            raise ValueError("saved release requires a canonical credential-free HTTPS locator")
        if any(part in {".", "..", ""} for part in value.split("/", 3)[-1].split("/")):
            raise ValueError("saved release locator path must be canonical")
        return value

    @field_validator("source_id", "release_id", "version", mode="before")
    @classmethod
    def release_tokens_are_exact(cls, value: object) -> str:
        """Reject padded or free-form release identifiers before normalization."""
        if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,199}", value) is None:
            raise ValueError("saved release identifiers require bounded exact tokens")
        return value

    @model_validator(mode="after")
    def binding_is_consistent(self) -> SavedReleaseSnapshot:
        """Detect changes to a frozen supplied descriptor, not an authenticated forgery."""
        payload = self.model_dump(mode="json", exclude={"binding_sha256"})
        if canonical_json_sha256(payload) != self.binding_sha256:
            raise ValueError("saved release descriptor does not match its binding digest")
        return self


class SavedReleaseProvenance(_ContractModel):
    """One selected child bound to its containing saved-release snapshot."""

    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["saved-release-provenance/v1"] = "saved-release-provenance/v1"
    snapshot: SavedReleaseSnapshot
    path: PortablePath
    candidate: PackageCandidateIdentity

    @model_validator(mode="after")
    def source_revision_matches(self) -> SavedReleaseProvenance:
        """Keep child identity in the containing snapshot's source revision."""
        require_path = re.fullmatch(r"skills/[a-z0-9]+(?:[._-][a-z0-9]+)*", self.path)
        if not require_path or self.candidate.source_revision != self.snapshot.root_candidate.source_revision:
            raise ValueError("saved child path and revision must bind the whole-plugin snapshot")
        return self


class SavedReleasePackageSource(_ContractModel):
    """Saved-source representation without a fabricated repository field."""

    schema_version: Literal["saved-release-package-source/v1"] = "saved-release-package-source/v1"
    package_id: PackageId
    provenance: SavedReleaseProvenance
    source_kind: Literal[PackageSourceKind.EXTERNAL] = PackageSourceKind.EXTERNAL

    @model_validator(mode="after")
    def source_matches_child(self) -> SavedReleasePackageSource:
        """Retain the exact selected child rather than its whole-plugin digest."""
        if self.package_id != self.provenance.candidate.package_id:
            raise ValueError("saved source package must match its selected child")
        return self


class NormalizedPackageV2(NormalizedPackage):
    """Additive normalized saved-release package; old v1 source stays unchanged."""

    schema_version: Literal["normalized-package/v2"] = "normalized-package/v2"
    source: SavedReleasePackageSource


__all__ = [
    "IntakeChecks",
    "IntakeDecision",
    "IntakeDecisionStatus",
    "NormalizedPackage",
    "NormalizedPackageV2",
    "OwnershipState",
    "PackageCandidateIdentity",
    "PackageLifecycleState",
    "PackageOwner",
    "PackageSource",
    "PackageSourceKind",
    "PluginIdentity",
    "SavedReleasePackageSource",
    "SavedReleaseProvenance",
    "SavedReleaseSnapshot",
    "SkillIdentity",
]
