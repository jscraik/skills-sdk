"""Whole-plugin local build and hardening evidence, without archive authority."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.package_safety import unsafe_package_path_reason
from skills_sdk.models.inventory import Sha256, _ContractModel
from skills_sdk.models.plugin import PluginPackageValidation
from skills_sdk.models.plugin_presentation import PluginPresentationCheck


class _LocalPluginEvidence(_ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False, revalidate_instances="always")
    mutation_performed: Literal[False] = False
    archive_emitted: Literal[False] = False
    publication_performed: Literal[False] = False
    execution_authorized: Literal[False] = False
    release_ready: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def canonical_input(cls, value: object) -> object:
        """Inspect copied instances before serialization can discard forged members."""
        if isinstance(value, BaseModel):
            if type(value) is not cls or value.__pydantic_extra__:
                raise ValueError("local plugin evidence requires its canonical model")
            if set(value.__dict__) - set(cls.model_fields):
                raise ValueError("local plugin evidence contains unknown copied fields")
            value = value.__dict__
        if type(value) is not dict:
            raise ValueError("local plugin evidence requires an object")
        for name in (
            "mutation_performed",
            "archive_emitted",
            "publication_performed",
            "execution_authorized",
            "release_ready",
        ):
            if name in value and value[name] is not False:
                raise ValueError("local plugin evidence cannot grant or coerce authority")
        return value


class PluginBuildReceipt(_LocalPluginEvidence):
    """Deterministic build over a complete capture, including its permission ledger."""

    schema_version: Literal["plugin-build/v1"] = "plugin-build/v1"
    status: Literal["built", "blocked"]
    validation: PluginPackageValidation
    build_digest: Sha256 | None = None

    @model_validator(mode="after")
    def bind_build(self) -> Self:
        """A build must retain passing versioned capture and its exact canonical digest."""
        capture = self.validation
        valid = (
            capture.status == "pass" and capture.manifest is not None and bool((capture.manifest.version or "").strip())
        )
        if (self.status == "built") != valid:
            raise ValueError("build status must agree with the complete versioned capture")
        expected = canonical_json_sha256(capture.model_dump(mode="json")) if valid else None
        if self.build_digest != expected:
            raise ValueError("build digest must bind complete capture, children, root metadata and modes")
        return self


class PluginHardeningPolicy(_ContractModel):
    """Local structural budgets; presentation approval remains a separate supplied assertion."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    max_file_count: int = Field(default=1024, strict=True, ge=1, le=1024)
    max_total_bytes: int = Field(default=64 * 1024 * 1024, strict=True, ge=1, le=64 * 1024 * 1024)
    require_readme: bool = Field(default=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def inspect_policy(cls, value: object) -> object:
        """Retain unknown copied fields for normal extra-field rejection."""
        if isinstance(value, BaseModel):
            if type(value) is not cls or value.__pydantic_extra__:
                raise ValueError("hardening policy requires its canonical model")
            return value.__dict__
        return value


def plugin_hardening_blockers(
    build: PluginBuildReceipt,
    fresh: PluginPackageValidation,
    presentation: PluginPresentationCheck | None,
    policy: PluginHardeningPolicy,
    source_stable: bool = True,
) -> tuple[str, ...]:
    """Derive structural blockers; never infer authenticated review or release clearance."""
    blocked: list[str] = []
    if build.status != "built":
        blocked.append("plugin_build_blocked")
    if not source_stable or fresh.status != "pass" or fresh != build.validation:
        blocked.append("plugin_source_changed_or_blocked")
    files = build.validation.files
    if any(unsafe_package_path_reason(item.path) is not None for item in files):
        blocked.append("plugin_forbidden_path")
    if len(files) > policy.max_file_count or sum(item.size_bytes for item in files) > policy.max_total_bytes:
        blocked.append("plugin_size_budget")
    if policy.require_readme and not any(item.path == "README.md" for item in files):
        blocked.append("plugin_readme_required")
    if any(item.permission_mode & 0o022 for item in files):
        blocked.append("plugin_writable_by_others")
    if presentation is None or presentation.status != "pass":
        blocked.append("plugin_presentation_required")
    elif (
        presentation.candidate != fresh.candidate
        or presentation.mode_manifest_sha256 != fresh.mode_manifest_sha256
        or fresh.manifest is None
        or presentation.openai_settings_sha256 != fresh.manifest.openai_settings_sha256
        or presentation.openai_settings_source != fresh.manifest.openai_settings_source
        or any(
            (image.path, image.sha256, image.size_bytes)
            not in {(item.path, item.sha256, item.size_bytes) for item in fresh.files}
            for image in presentation.images
        )
    ):
        blocked.append("plugin_presentation_mismatch")
    return tuple(blocked)


class PluginHardeningReceipt(_LocalPluginEvidence):
    """Fresh-source local hardening result; supplied approvals are not authenticated here."""

    schema_version: Literal["plugin-hardening/v1"] = "plugin-hardening/v1"
    status: Literal["pass", "blocked"]
    build: PluginBuildReceipt
    fresh_validation: PluginPackageValidation
    presentation: PluginPresentationCheck | None = None
    policy: PluginHardeningPolicy = PluginHardeningPolicy()
    source_stable: bool = Field(strict=True)
    blockers: tuple[str, ...]

    @model_validator(mode="after")
    def bind_hardening(self) -> Self:
        """Recompute every blocker so copied positive results cannot conceal failed checks."""
        expected = plugin_hardening_blockers(
            self.build, self.fresh_validation, self.presentation, self.policy, self.source_stable
        )
        if self.blockers != expected or (self.status == "blocked") != bool(expected):
            raise ValueError("hardening result must retain all derived blockers")
        return self
