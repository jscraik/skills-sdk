"""Versioned inventory contracts for retained skills and plugins."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path

PackageId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")]
GitRevision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PortablePath = Annotated[str, StringConstraints(min_length=1)]


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PackageType(StrEnum):
    """Canonical package categories admitted by the Foundry."""

    SKILL = "skill"
    PLUGIN = "plugin"


class PackageDisposition(StrEnum):
    """Explicit inventory outcomes; none imply mutation."""

    ADMIT_TO_FOUNDRY = "admit_to_foundry"
    MERGE_WITH_EXISTING = "merge_with_existing"
    RETAIN_EXTERNAL_SOURCE = "retain_external_source"
    RUNTIME_ONLY = "runtime_only"
    SDK_FIXTURE_ONLY = "sdk_fixture_only"
    ARCHIVE_WITH_PROVENANCE = "archive_with_provenance"
    REJECT_DUPLICATE = "reject_duplicate"
    REJECT_UNSAFE = "reject_unsafe"
    NEEDS_OWNER_DECISION = "needs_owner_decision"


class RuntimeVisibility(StrEnum):
    """Observed runtime surfaces, kept separate from canonical ownership."""

    USER_AGENTS = "user_agents"
    PROJECT_AGENTS = "project_agents"
    CODEX_PLUGIN_CACHE = "codex_plugin_cache"
    NONE = "none"


class RiskClass(StrEnum):
    """Inventory risk classification before admission."""

    NONE = "none"
    REVIEW = "review"
    BLOCKED = "blocked"


class SourceProvenance(_ContractModel):
    """Immutable source identity retained for an inventory candidate."""

    repository: NonEmptyText
    revision: GitRevision
    path: PortablePath
    content_sha256: Sha256

    @field_validator("path")
    @classmethod
    def path_must_be_portable(cls, value: str) -> str:
        require_portable_relative_path(value)
        return value


class RightsStatus(_ContractModel):
    """Rights evidence required before canonical admission."""

    basis: Literal["authored", "license", "permission"]
    license: NonEmptyText
    evidence_ref: PortablePath

    @field_validator("evidence_ref")
    @classmethod
    def evidence_ref_must_be_portable(cls, value: str) -> str:
        require_portable_relative_path(value)
        return value


class FormatChecks(_ContractModel):
    """Format evidence recorded during read-only package inventory."""

    root_plugin_manifest: bool = False
    codex_adapter_manifest: bool = False


class PackageInventoryRecord(_ContractModel):
    """One read-only inventory record for a retained skill or plugin."""

    schema_version: Literal["package-inventory/v1"] = "package-inventory/v1"
    package_id: PackageId
    display_name: NonEmptyText | None = None
    package_type: PackageType
    current_path: PortablePath
    declared_version: NonEmptyText | None = None
    owner: NonEmptyText
    source: SourceProvenance | None = None
    rights: RightsStatus | None = None
    direct_consumers: tuple[PortablePath, ...] = ()
    runtime_visibility: tuple[RuntimeVisibility, ...] = ()
    duplicate_of: PackageId | None = None
    risk: RiskClass = RiskClass.NONE
    external_dependencies: tuple[NonEmptyText, ...] = ()
    tessl_identity: NonEmptyText | None = None
    blocker_codes: tuple[NonEmptyText, ...] = ()
    format_checks: FormatChecks | None = None
    intended_disposition: PackageDisposition

    @field_validator("current_path")
    @classmethod
    def current_path_must_be_portable(cls, value: str) -> str:
        require_portable_relative_path(value)
        return value

    @field_validator("direct_consumers")
    @classmethod
    def consumers_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            require_portable_relative_path(value)
        return values

    @model_validator(mode="after")
    def duplicate_requires_target(self) -> PackageInventoryRecord:
        if self.duplicate_of == self.package_id:
            raise ValueError("duplicate_of must identify a different package")
        if self.intended_disposition == PackageDisposition.REJECT_DUPLICATE and self.duplicate_of is None:
            raise ValueError("reject_duplicate requires duplicate_of")
        if self.intended_disposition == PackageDisposition.ADMIT_TO_FOUNDRY and (
            self.source is None or self.rights is None
        ):
            raise ValueError("admit_to_foundry requires source and rights evidence")
        return self


class PackageInventory(_ContractModel):
    """A deterministic, read-only inventory snapshot."""

    schema_version: Literal["package-inventory-set/v1"] = "package-inventory-set/v1"
    source_revision: GitRevision
    records: tuple[PackageInventoryRecord, ...]

    @model_validator(mode="after")
    def package_ids_are_unique(self) -> PackageInventory:
        package_ids = [record.package_id for record in self.records]
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("inventory package_id values must be unique")
        return self
