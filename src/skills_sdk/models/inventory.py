"""Versioned inventory contracts for retained skills and plugins."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, WithJsonSchema, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path

PackageId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")]
GitRevision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PortablePath = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 1,
            "x-skills-sdk-portable-path": True,
        }
    ),
]


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


class RecommendedMechanism(StrEnum):
    """The smallest useful packaging mechanism for a candidate."""

    STANDALONE_SKILL = "standalone_skill"
    PLUGIN_BUNDLE = "plugin_bundle"
    EXTERNAL_SOURCE = "external_source"
    ARCHIVE = "archive"
    REJECT = "reject"


class ValueDecision(StrEnum):
    """The evidence-backed value decision for an inventory candidate."""

    RETAIN = "retain"
    MERGE = "merge"
    REPLACE = "replace"
    RETIRE = "retire"


class MantraStatus(StrEnum):
    """Assessment status for one engineering-mantra principle."""

    PASS = "pass"
    REVISE = "revise"
    REJECT = "reject"


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


class MantraPrinciple(_ContractModel):
    """Candidate-bound evidence for one engineering-mantra principle."""

    status: MantraStatus
    evidence: tuple[NonEmptyText, ...]

    @field_validator("evidence")
    @classmethod
    def evidence_must_be_present(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("mantra evidence must contain at least one reference")
        return values


class MantraAssessment(_ContractModel):
    """The complete nine-part assessment bound to one exact candidate."""

    source_revision: GitRevision
    content_sha256: Sha256
    taste: MantraPrinciple
    thin_surfaces: MantraPrinciple
    strong_guardrails: MantraPrinciple
    simplicity: MantraPrinciple
    progressive_disclosure: MantraPrinciple
    durable_memory: MantraPrinciple
    valuemaxxing: MantraPrinciple
    self_improvement: MantraPrinciple
    professional_output: MantraPrinciple
    overall: MantraStatus

    @model_validator(mode="after")
    def overall_matches_principles(self) -> MantraAssessment:
        statuses = (
            self.taste.status,
            self.thin_surfaces.status,
            self.strong_guardrails.status,
            self.simplicity.status,
            self.progressive_disclosure.status,
            self.durable_memory.status,
            self.valuemaxxing.status,
            self.self_improvement.status,
            self.professional_output.status,
        )
        expected = (
            MantraStatus.REJECT
            if MantraStatus.REJECT in statuses
            else MantraStatus.REVISE
            if MantraStatus.REVISE in statuses
            else MantraStatus.PASS
        )
        if self.overall != expected:
            raise ValueError(f"mantra overall must be {expected.value} for the principle statuses")
        return self


class PackageInventoryRecord(_ContractModel):
    """One read-only inventory record for a retained skill or plugin."""

    schema_version: Literal["package-inventory/v1"] = "package-inventory/v1"
    package_id: PackageId
    display_name: NonEmptyText | None = None
    package_type: PackageType
    current_path: PortablePath
    declared_version: NonEmptyText | None = None
    owner: NonEmptyText
    user_outcome: NonEmptyText
    distinctive_value: NonEmptyText
    maintenance_cost: NonEmptyText
    context_cost: NonEmptyText
    overlap_with_existing: tuple[NonEmptyText, ...] = ()
    recommended_mechanism: RecommendedMechanism
    value_decision: ValueDecision
    mantra: MantraAssessment
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
        if self.source is not None and (
            self.mantra.source_revision != self.source.revision
            or self.mantra.content_sha256 != self.source.content_sha256
        ):
            raise ValueError("mantra assessment must bind the exact source revision and content digest")
        if self.package_type == PackageType.SKILL and self.recommended_mechanism == RecommendedMechanism.PLUGIN_BUNDLE:
            raise ValueError("a skill cannot recommend plugin_bundle without a plugin package boundary")
        if self.package_type == PackageType.PLUGIN and self.recommended_mechanism == (
            RecommendedMechanism.STANDALONE_SKILL
        ):
            raise ValueError("a plugin cannot recommend standalone_skill")
        if self.value_decision == ValueDecision.MERGE and not self.overlap_with_existing:
            raise ValueError("merge value decision requires overlap_with_existing evidence")
        if self.value_decision == ValueDecision.RETIRE and self.intended_disposition in (
            PackageDisposition.ADMIT_TO_FOUNDRY,
            PackageDisposition.MERGE_WITH_EXISTING,
        ):
            raise ValueError("retire value decision cannot admit or merge a package")
        if (
            self.intended_disposition
            in (
                PackageDisposition.ADMIT_TO_FOUNDRY,
                PackageDisposition.MERGE_WITH_EXISTING,
            )
            and self.mantra.overall != MantraStatus.PASS
        ):
            raise ValueError("admission and merge require a passing mantra assessment")
        return self


class PackageInventory(_ContractModel):
    """A read-only inventory snapshot preserving caller-supplied record order."""

    schema_version: Literal["package-inventory-set/v1"] = "package-inventory-set/v1"
    source_revision: GitRevision
    records: tuple[PackageInventoryRecord, ...]

    @model_validator(mode="after")
    def package_ids_are_unique(self) -> PackageInventory:
        if any(record.schema_version != "package-inventory/v1" for record in self.records):
            raise ValueError("package-inventory-set/v1 requires package-inventory/v1 records")
        package_ids = [record.package_id for record in self.records]
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("inventory package_id values must be unique")
        return self


class ValueDecisionV2(StrEnum):
    """Value decision including an explicit unresolved review state."""

    NEEDS_REVIEW = "needs_review"
    RETAIN = "retain"
    MERGE = "merge"
    REPLACE = "replace"
    RETIRE = "retire"


class PackageInventoryRecordV2(PackageInventoryRecord):
    """Version-two inventory record with typed pending value review."""

    schema_version: Literal["package-inventory/v2"] = "package-inventory/v2"
    value_decision: ValueDecisionV2

    @model_validator(mode="after")
    def pending_value_review_is_blocked(self) -> PackageInventoryRecordV2:
        if self.value_decision == ValueDecisionV2.NEEDS_REVIEW and (
            self.intended_disposition != PackageDisposition.NEEDS_OWNER_DECISION
            or "value_review_required" not in self.blocker_codes
        ):
            raise ValueError("needs_review value decision requires needs_owner_decision and value_review_required")
        return self


class PackageInventoryV2(_ContractModel):
    """Version-two read-only inventory snapshot preserving caller-supplied record order."""

    schema_version: Literal["package-inventory-set/v2"] = "package-inventory-set/v2"
    source_revision: GitRevision
    records: tuple[PackageInventoryRecordV2, ...]

    @model_validator(mode="after")
    def package_ids_are_unique(self) -> PackageInventoryV2:
        if any(record.schema_version != "package-inventory/v2" for record in self.records):
            raise ValueError("package-inventory-set/v2 requires package-inventory/v2 records")
        package_ids = [record.package_id for record in self.records]
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("inventory package_id values must be unique")
        return self
