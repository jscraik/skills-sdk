"""Read-only portable plugin capture; not admission or release clearance."""

from __future__ import annotations

import hashlib
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity, SkillIdentity, _candidate_package_id
from skills_sdk.models.packaging import PackageFileRole, PackageManifestFile, _file_role
from skills_sdk.models.validation import SkillPackageFinding, SkillPackageValidation, ValidationSeverity

PLUGIN_SCHEMA_URI = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"


def _is_skill_entrypoint(path: str) -> bool:
    """Recognise only literal immediate skill entrypoints, not lookalike names."""
    parts = path.split("/")
    return len(parts) == 3 and parts[0] == "skills" and bool(parts[1]) and parts[2] == "SKILL.md"


def plugin_candidate_id(name: str) -> str:
    """Map every portable name into frozen SDK PackageId without lossy aliases."""
    return "plugin-" + hashlib.sha256(name.encode("utf-8")).hexdigest()


def _normalise(value: object, budget: list[int], depth: int = 0) -> object:
    """Inspect copied model members before serializers can hide forged input."""
    budget[0] -= 1
    if budget[0] < 0 or depth > 40:
        raise ValueError("plugin evidence exceeds its input budget")
    if isinstance(value, BaseModel):
        if type(value) not in _PLUGIN_MODELS or value.__pydantic_extra__:
            raise ValueError("plugin evidence requires canonical SDK model classes")
        if set(value.__dict__) - set(type(value).model_fields):
            raise ValueError("plugin evidence contains unknown copied members")
        value = value.__dict__
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("plugin evidence requires string keys")
        if "size_bytes" in value and type(value["size_bytes"]) is not int:
            raise ValueError("plugin evidence requires integer file sizes without coercion")
        for flag in ("mutation_performed", "execution_authorized", "release_ready"):
            if flag in value and value[flag] is not False:
                raise ValueError("plugin evidence cannot coerce authority flags")
        return {key: _normalise(item, budget, depth + 1) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_normalise(item, budget, depth + 1) for item in value]
    if type(value) in (PackageFileRole, ValidationSeverity):
        return value.value
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("plugin evidence requires canonical JSON values")


class PortablePluginManifest(_ContractModel):
    """Bounded projection of root metadata; optional base fields stay optional."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False, revalidate_instances="always")
    manifest_schema_uri: Literal["https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"] = PLUGIN_SCHEMA_URI
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
    version: str | None = None
    description: str | None = None
    source_sha256: Sha256
    openai_settings_source: Literal["inline", "compatibility", "none"] = "none"
    openai_settings_sha256: Sha256 | None = None

    @field_validator("name")
    @classmethod
    def portable_name(cls, value: str) -> str:
        """Reject repeated separators in an otherwise valid portable plugin name."""
        if "--" in value or ".." in value:
            raise ValueError("portable plugin name cannot contain repeated separators")
        return value

    @model_validator(mode="after")
    def selected_settings(self) -> Self:
        """Require a settings digest exactly when a settings source is selected."""
        if (self.openai_settings_source == "none") != (self.openai_settings_sha256 is None):
            raise ValueError("selected settings require exactly one object digest")
        return self


class PluginCapturedFile(_ContractModel):
    """Captured bytes plus ordinary permissions; no new legacy file role."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False, revalidate_instances="always")
    path: PortablePath
    sha256: Sha256
    size_bytes: int = Field(strict=True, ge=0, le=16 * 1024 * 1024)
    permission_mode: int = Field(strict=True, ge=0, le=0o777)

    @field_validator("path")
    @classmethod
    def portable_path(cls, value: str) -> str:
        """Require a UTF-8 encodable portable relative path for a captured file."""
        value.encode("utf-8")
        require_portable_relative_path(value)
        return value


class PluginSkillBinding(_ContractModel):
    """The existing standalone validator result for one direct skill subtree."""

    path: PortablePath
    validation: SkillPackageValidation

    @field_validator("path")
    @classmethod
    def direct_skill(cls, value: str) -> str:
        """Require the binding path to name a direct child of skills/."""
        path = require_portable_relative_path(value)
        if len(path.parts) != 2 or path.parts[0] != "skills":
            raise ValueError("plugin skills must be direct children of skills/")
        return value


class PluginValidationPolicy(_ContractModel):
    """Opt-in SDK metadata policy, separate from portable base conformance."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    require_version: bool = Field(default=False, strict=True)
    require_description: bool = Field(default=False, strict=True)

    @model_validator(mode="before")
    @classmethod
    def canonical_policy(cls, value: object) -> object:
        """Normalize policy input within a fixed budget before validating its fields."""
        return _normalise(value, [128])


def _validate_child(binding: PluginSkillBinding, files: tuple[PluginCapturedFile, ...], revision: str) -> None:
    """Require child files, roles, identity and revision to match the captured subtree."""
    child, prefix = binding.validation, binding.path + "/"
    expected = tuple(
        (item.path[len(prefix) :], item.sha256, item.size_bytes, _file_role(item.path[len(prefix) :]))
        for item in files
        if item.path.startswith(prefix)
    )
    actual = tuple((item.path, item.sha256, item.size_bytes, item.role) for item in child.files)
    if expected != actual or child.candidate is None:
        raise ValueError("child validation must cover its entire captured subtree")
    if child.candidate.source_revision != revision or child.candidate.content_sha256 != candidate_content_sha256(
        child.files
    ):
        raise ValueError("child candidate must bind captured content and revision")
    leaf = binding.path.split("/")[1]
    if child.candidate.package_id != _candidate_package_id(leaf, child.candidate.content_sha256):
        raise ValueError("child candidate must match the direct skill directory")
    if child.identity is not None and (
        child.identity.name != leaf or child.identity.package_id != child.candidate.package_id
    ):
        raise ValueError("child identity must bind the direct skill name")


def _validate_component_kinds(paths: set[str], findings: tuple[SkillPackageFinding, ...]) -> None:
    """Retain kind blockers proved by files or their nonempty ancestor paths."""
    invalid_kind = "skills" in paths or any(
        path.startswith("mcp.json/")
        or (len(path.split("/")) > 3 and _is_skill_entrypoint("/".join(path.split("/")[:3])))
        for path in paths
    )
    if invalid_kind and not any(
        item.code == "plugin_component_kind_invalid" and item.severity == ValidationSeverity.BLOCKER
        for item in findings
    ):
        raise ValueError("captured component kinds require their blocker finding")


class PluginPackageValidation(_ContractModel):
    """Whole-plugin structural proof, with no execution or release authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False, revalidate_instances="always")
    schema_version: Literal["plugin-package-validation/v1"] = "plugin-package-validation/v1"
    status: Literal["pass", "blocked"]
    candidate: PackageCandidateIdentity | None = None
    manifest: PortablePluginManifest | None = None
    policy: PluginValidationPolicy = PluginValidationPolicy()
    files: tuple[PluginCapturedFile, ...] = Field(default=(), max_length=1024)
    mode_manifest_sha256: Sha256 | None = None
    skills: tuple[PluginSkillBinding, ...] = Field(default=(), max_length=128)
    findings: tuple[SkillPackageFinding, ...] = Field(default=(), max_length=2048)
    mutation_performed: Literal[False] = False
    execution_authorized: Literal[False] = False
    release_ready: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def copied_inputs(cls, value: object) -> object:
        """Normalize the full envelope and reject forged model members before validation."""
        return _normalise(value, [131072])

    @model_validator(mode="after")
    def bind_capture(self) -> Self:
        """Require status, digests, manifest and children to agree with the retained capture."""
        blockers = any(item.severity == ValidationSeverity.BLOCKER for item in self.findings)
        if (self.status == "blocked") != blockers:
            raise ValueError("plugin status must agree with blocker findings")
        if self.candidate is None:
            if self.status != "blocked" or self.manifest or self.files or self.skills or self.mode_manifest_sha256:
                raise ValueError("unbound plugin input must be an empty blocked capture")
            return self
        if self.manifest is None or not self.files:
            raise ValueError("bound plugin validation requires root manifest and files")
        paths = tuple(item.path for item in self.files)
        if paths != tuple(sorted(set(paths))) or "plugin.json" not in paths:
            raise ValueError("plugin capture requires unique sorted paths and root plugin.json")
        path_set = set(paths)
        _validate_component_kinds(path_set, self.findings)
        if any(
            "/".join(path.split("/")[:index]) in path_set for path in paths for index in range(1, len(path.split("/")))
        ):
            raise ValueError("captured file cannot also be a directory ancestor")
        if sum(item.size_bytes for item in self.files) > 64 * 1024 * 1024:
            raise ValueError("plugin capture exceeds its byte budget")
        if self.candidate.package_id != plugin_candidate_id(self.manifest.name):
            raise ValueError("plugin candidate must bind the canonical portable name")
        if self.candidate.content_sha256 != candidate_content_sha256(self.files):
            raise ValueError("plugin candidate digest must bind the complete capture")
        if self.mode_manifest_sha256 != canonical_json_sha256([item.model_dump(mode="json") for item in self.files]):
            raise ValueError("plugin permissions require the exact captured mode digest")
        manifest_file = next(item for item in self.files if item.path == "plugin.json")
        if manifest_file.sha256 != self.manifest.source_sha256:
            raise ValueError("manifest projection must bind captured root bytes")
        if self.manifest.openai_settings_source == "compatibility" and ".codex-plugin/plugin.json" not in paths:
            raise ValueError("compatibility settings require the captured overlay")
        expected = tuple(sorted(path.rsplit("/", 1)[0] for path in paths if _is_skill_entrypoint(path)))
        if tuple(item.path for item in self.skills) != expected:
            raise ValueError("retained children must equal all discovered immediate skills")
        for child in self.skills:
            _validate_child(child, self.files, self.candidate.source_revision)
        if self.status == "pass":
            if any(item.validation.status != "pass" for item in self.skills):
                raise ValueError("passing plugin cannot contain blocked skills")
            if self.policy.require_version and not (self.manifest.version or "").strip():
                raise ValueError("passing plugin must satisfy its SDK version policy")
            if self.policy.require_description and not (self.manifest.description or "").strip():
                raise ValueError("passing plugin must satisfy its SDK description policy")
        return self


_PLUGIN_MODELS = frozenset(
    {
        PortablePluginManifest,
        PluginCapturedFile,
        PluginSkillBinding,
        PluginValidationPolicy,
        PluginPackageValidation,
        PackageCandidateIdentity,
        PackageManifestFile,
        SkillIdentity,
        SkillPackageValidation,
        SkillPackageFinding,
    }
)

__all__ = [
    "PluginCapturedFile",
    "PluginPackageValidation",
    "PluginSkillBinding",
    "PluginValidationPolicy",
    "PortablePluginManifest",
]
