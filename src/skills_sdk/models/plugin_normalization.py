"""Candidate-bound proof for explicit standalone-skill plugin normalization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictStr, StringConstraints, field_validator, model_validator

from skills_sdk.models.intake import SkillPackageIntakeReceipt, _intake_evidence_data
from skills_sdk.models.inventory import PackageType, _ContractModel
from skills_sdk.models.package import IntakeDecisionStatus, NormalizedPackage, PackageLifecycleState
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.plugin import PLUGIN_MANIFEST_MAX_BYTES, PLUGIN_SCHEMA_URI, PluginPackageValidation

_NormalizationPluginName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$", max_length=64)]


def _canonical_normalization_manifest(name: str, version: str, description: str) -> bytes:
    """Render the only root metadata this operation creates within the shared parser budget."""
    values = {"$schema": PLUGIN_SCHEMA_URI, "name": name, "version": version, "description": description}
    payload = (json.dumps(values, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(payload) > PLUGIN_MANIFEST_MAX_BYTES:
        raise ValueError("canonical normalization manifest exceeds one MiB")
    return payload


def _retained_validation_matches_source(
    source: SkillPackageIntakeReceipt, validation: PluginPackageValidation | None
) -> bool:
    """Allow blocked diagnostics but bind every retained passing proof to its sole source child."""
    return (
        validation is None
        or validation.status != "pass"
        or (
            source.candidate is not None
            and len(validation.skills) == 1
            and validation.skills[0].validation.candidate == source.candidate
        )
    )


class PluginNormalizationMetadata(_ContractModel):
    """Caller-owned canonical root-manifest metadata for a new plugin candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False, revalidate_instances="always")

    schema_version: Literal["plugin-normalization-metadata/v1"] = "plugin-normalization-metadata/v1"
    name: _NormalizationPluginName
    version: StrictStr = Field(min_length=1, max_length=PLUGIN_MANIFEST_MAX_BYTES)
    description: StrictStr = Field(min_length=1, max_length=PLUGIN_MANIFEST_MAX_BYTES)

    @field_validator("version", "description")
    @classmethod
    def canonical_required_text(cls, value: str) -> str:
        """Reject empty or padded caller metadata rather than silently rewriting it."""
        if not value or value != value.strip():
            raise ValueError("plugin version and description must be canonical non-empty text")
        return value

    @model_validator(mode="after")
    def bounded_manifest(self) -> PluginNormalizationMetadata:
        """Enforce aggregate encoded bytes, which structural JSON Schema cannot express."""
        _canonical_normalization_manifest(self.name, self.version, self.description)
        return self


def _prepared_output_matches_source(source: SkillPackageIntakeReceipt, validation: PluginPackageValidation) -> bool:
    """Bind prepared evidence to canonical root bytes and the exact admitted child file set."""
    manifest, identity = validation.manifest, source.validation.identity
    assert manifest is not None and manifest.version is not None and manifest.description is not None
    assert identity is not None
    metadata = PluginNormalizationMetadata(
        name=manifest.name, version=manifest.version, description=manifest.description
    )
    payload = _canonical_normalization_manifest(metadata.name, metadata.version, metadata.description)
    digest = hashlib.sha256(payload).hexdigest()
    expected = [("plugin.json", digest, len(payload))]
    expected.extend(
        (f"skills/{identity.name}/{item.path}", item.sha256, item.size_bytes) for item in source.validation.files
    )
    observed = [(item.path, item.sha256, item.size_bytes) for item in validation.files]
    return (
        observed == sorted(expected)
        and manifest.source_sha256 == digest
        and manifest.openai_settings_source == "none"
        and manifest.openai_settings_sha256 is None
        and next(item.permission_mode for item in validation.files if item.path == "plugin.json") == 0o644
    )


class PluginNormalizationReceipt(_ContractModel):
    """Retain source admission and fresh whole-plugin proof without release authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["plugin-normalization/v1"] = "plugin-normalization/v1"
    status: Literal["prepared", "blocked"]
    source_intake: SkillPackageIntakeReceipt
    plugin_validation: PluginPackageValidation | None = None
    normalized_package: NormalizedPackage | None = Field(
        default=None, json_schema_extra={"properties": {"dependencies": {"maxItems": 0}}}
    )
    blocker: PackageReceiptBlocker | None = None
    candidate_created: bool = False
    source_mutated: Literal[False] = False
    network_used: Literal[False] = False
    execution_performed: Literal[False] = False
    release_ready: Literal[False] = False

    @field_validator(
        "candidate_created", "source_mutated", "network_used", "execution_performed", "release_ready", mode="before"
    )
    @classmethod
    def strict_evidence_flags(cls, value: object) -> object:
        """Reject non-boolean evidence before Pydantic can coerce it."""
        if type(value) is not bool:
            raise ValueError("normalization evidence flags must be booleans")
        return value

    @field_validator("source_intake", mode="before")
    @classmethod
    def strict_source_intake_flags(cls, value: object) -> object:
        """Check retained intake flags before the frozen model can coerce them."""
        value = _intake_evidence_data(value)
        if isinstance(value, Mapping):
            for field in ("mutation_performed", "network_used", "execution_performed"):
                if field in value and type(value[field]) is not bool:
                    raise ValueError("retained intake evidence flags must be booleans")
            validation = value.get("validation")
            if (
                isinstance(validation, Mapping)
                and "mutation_performed" in validation
                and type(validation["mutation_performed"]) is not bool
            ):
                raise ValueError("retained validation mutation flag must be a boolean")
        return value

    @model_validator(mode="after")
    def bind_source_and_plugin(self) -> PluginNormalizationReceipt:
        """Require a fresh single-child plugin proof tied to admitted source evidence."""
        source = self.source_intake
        if not _retained_validation_matches_source(source, self.plugin_validation):
            raise ValueError("retained passing plugin validation must bind the exact standalone source candidate")
        if self.status == "blocked":
            if self.blocker is None or self.normalized_package is not None:
                raise ValueError("blocked normalization requires a blocker and no normalized package")
            if self.plugin_validation is not None and not self.candidate_created:
                raise ValueError("plugin validation requires a created normalization candidate")
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
        if normalized.lifecycle is not PackageLifecycleState.NORMALIZED:
            raise ValueError("prepared normalization must retain the normalized lifecycle")
        if normalized.dependencies:
            raise ValueError("standalone normalization cannot introduce unverified plugin dependencies")
        if not validation.policy.require_version or not validation.policy.require_description:
            raise ValueError("prepared normalization requires version and description validation policy")
        if not (validation.manifest.version or "").strip() or not (validation.manifest.description or "").strip():
            raise ValueError("prepared normalization requires nonempty manifest version and description")
        if not _prepared_output_matches_source(source, validation):
            raise ValueError("prepared normalization must bind its canonical manifest and exact admitted source files")
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
