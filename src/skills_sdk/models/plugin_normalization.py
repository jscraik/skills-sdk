"""Candidate-bound proof for explicit standalone-skill plugin normalization."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, StrictStr, field_validator, model_validator

from skills_sdk.models.intake import SkillPackageIntakeReceipt
from skills_sdk.models.inventory import PackageType, _ContractModel
from skills_sdk.models.package import IntakeDecisionStatus, NormalizedPackage, PluginName
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.plugin import PluginPackageValidation


class PluginNormalizationMetadata(_ContractModel):
    """Caller-owned canonical root-manifest metadata for a new plugin candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False, revalidate_instances="always")

    schema_version: Literal["plugin-normalization-metadata/v1"] = "plugin-normalization-metadata/v1"
    name: PluginName = Field(max_length=64)
    version: StrictStr
    description: StrictStr

    @field_validator("name")
    @classmethod
    def portable_plugin_name(cls, value: str) -> str:
        """Reject repeated separators excluded by the canonical plugin manifest."""
        if "--" in value or ".." in value:
            raise ValueError("plugin name cannot contain repeated separators")
        return value

    @field_validator("version", "description")
    @classmethod
    def canonical_required_text(cls, value: str) -> str:
        """Reject empty or padded caller metadata rather than silently rewriting it."""
        if not value or value != value.strip():
            raise ValueError("plugin version and description must be canonical non-empty text")
        return value


class PluginNormalizationReceipt(_ContractModel):
    """Retain source admission and fresh whole-plugin proof without release authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["plugin-normalization/v1"] = "plugin-normalization/v1"
    status: Literal["prepared", "blocked"]
    source_intake: SkillPackageIntakeReceipt
    plugin_validation: PluginPackageValidation | None = None
    normalized_package: NormalizedPackage | None = None
    blocker: PackageReceiptBlocker | None = None
    candidate_created: bool = False
    source_mutated: Literal[False] = False
    network_used: Literal[False] = False
    execution_performed: Literal[False] = False
    release_ready: Literal[False] = False

    @model_validator(mode="after")
    def bind_source_and_plugin(self) -> PluginNormalizationReceipt:
        """Require a fresh single-child plugin proof tied to admitted source evidence."""
        source = self.source_intake
        if self.status == "blocked":
            if self.blocker is None or self.normalized_package is not None:
                raise ValueError("blocked normalization requires a blocker and no normalized package")
            return self
        if not self.candidate_created or self.blocker is not None or self.plugin_validation is None:
            raise ValueError("prepared normalization requires a created candidate and fresh plugin validation")
        if source.status != "normalized" or source.decision is None:
            raise ValueError("prepared normalization requires resolved standalone intake")
        if source.decision.decision is not IntakeDecisionStatus.ADMIT:
            raise ValueError("prepared normalization requires admitted provenance, rights, and ownership")
        if source.normalized_package is None or source.candidate is None:
            raise ValueError("prepared normalization requires the full standalone intake receipt")
        validation, normalized = self.plugin_validation, self.normalized_package
        if validation.status != "pass" or validation.candidate is None or validation.manifest is None:
            raise ValueError("prepared normalization requires passing complete-plugin validation")
        if normalized is None or normalized.package_type is not PackageType.PLUGIN:
            raise ValueError("prepared normalization requires a normalized plugin identity")
        if len(validation.skills) != 1:
            raise ValueError("standalone normalization must produce exactly one contained skill")
        child = validation.skills[0]
        if child.validation.candidate != source.candidate:
            raise ValueError("plugin child must retain the exact standalone skill candidate identity")
        if normalized.identity.package_id != validation.candidate.package_id:
            raise ValueError("normalized plugin and whole-plugin candidate identities must match")
        if normalized.owner != source.normalized_package.owner:
            raise ValueError("normalization must preserve source ownership and rights evidence")
        provenance = normalized.source.provenance
        context = source.context
        if (
            normalized.source.package_id != validation.candidate.package_id
            or provenance.repository != context.source_repository
            or provenance.revision != context.source_revision
            or provenance.path != context.source_path
            or provenance.content_sha256 != validation.candidate.content_sha256
            or normalized.source.source_kind != context.source_kind
        ):
            raise ValueError("normalized plugin provenance must bind source and complete-plugin content")
        if (
            normalized.identity.name != validation.manifest.name
            or normalized.identity.version != validation.manifest.version
        ):
            raise ValueError("normalized plugin metadata must match the captured root manifest")
        return self


__all__ = ["PluginNormalizationMetadata", "PluginNormalizationReceipt"]
