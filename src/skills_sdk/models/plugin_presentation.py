"""Candidate-bound presentation assertions and offline assessment results."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.validation import SkillPackageFinding, ValidationSeverity

PresentationRole = Literal["logo", "composerIcon", "logoDark", "composerIconDark", "screenshot"]
PresentationFormat = Literal["png", "jpeg", "webp", "svg"]
EvidenceRef = Annotated[
    str,
    StringConstraints(
        strip_whitespace=False,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]

_ICON_ROLES = frozenset({"logo", "composerIcon", "logoDark", "composerIconDark"})
_BOOLEAN_FIELDS = frozenset(
    {
        "professional",
        "rights_confirmed",
        "recognisable",
        "small_size",
        "light_dark",
        "distinctive",
        "accurate",
        "mutation_performed",
        "execution_authorized",
        "release_ready",
        "archive_verified",
        "host_display_observed",
        "publication_verified",
    }
)


def _normalise(
    value: object,
    budget: list[int],
    active: set[int] | None = None,
    depth: int = 0,
) -> object:
    """Copy bounded canonical JSON values before Pydantic can hide forged input."""
    budget[0] -= 1
    if budget[0] < 0 or depth > 40:
        raise ValueError("presentation evidence exceeds its input budget")
    if isinstance(value, BaseModel):
        if type(value) not in _PRESENTATION_MODELS or value.__pydantic_extra__:
            raise ValueError("presentation evidence requires canonical SDK model classes")
        if set(value.__dict__) - set(type(value).model_fields):
            raise ValueError("presentation evidence contains unknown copied members")
        value = value.__dict__
    if type(value) is dict:
        containers = active if active is not None else set()
        identity = id(value)
        if identity in containers:
            raise ValueError("presentation evidence cannot contain cycles")
        containers.add(identity)
        try:
            if any(type(key) is not str for key in value):
                raise ValueError("presentation evidence requires string keys")
            for key in ("package_id", "source_revision", "content_sha256", "code"):
                if key in value and (type(value[key]) is not str or value[key] != value[key].strip()):
                    raise ValueError("presentation evidence requires canonical identifiers without padding")
            for key in _BOOLEAN_FIELDS & value.keys():
                if type(value[key]) is not bool and value[key] is not None:
                    raise ValueError("presentation booleans must not be coerced")
            return {key: _normalise(item, budget, containers, depth + 1) for key, item in value.items()}
        finally:
            containers.remove(identity)
    if type(value) in (list, tuple):
        containers = active if active is not None else set()
        identity = id(value)
        if identity in containers:
            raise ValueError("presentation evidence cannot contain cycles")
        containers.add(identity)
        try:
            return [_normalise(item, budget, containers, depth + 1) for item in value]
        finally:
            containers.remove(identity)
    if type(value) is ValidationSeverity:
        return value.value
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("presentation evidence requires finite numbers")
    if type(value) is str:
        value.encode("utf-8")
        if len(value) > 8192:
            raise ValueError("presentation evidence strings exceed their input budget")
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError("presentation evidence requires canonical JSON values")


class _PresentationModel(_ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False, revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def canonical_input(cls, value: object) -> object:
        return _normalise(value, [131072])


class PluginImageApproval(_PresentationModel):
    """Public-safe supplied approval for one exact candidate image."""

    schema_version: Literal["plugin-image-approval/v1"] = "plugin-image-approval/v1"
    candidate: PackageCandidateIdentity
    image_path: PortablePath
    image_sha256: Sha256
    kind: Literal["icon", "screenshot"]
    professional: Literal[True]
    rights_confirmed: Literal[True]
    recognisable: Literal[True] | None = None
    small_size: Literal[True] | None = None
    light_dark: Literal[True] | None = None
    distinctive: Literal[True] | None = None
    evidence_ref: EvidenceRef
    evidence_sha256: Sha256

    @field_validator("image_path")
    @classmethod
    def portable_image_path(cls, value: str) -> str:
        require_portable_relative_path(value)
        return value

    @model_validator(mode="after")
    def criteria_match_kind(self) -> Self:
        criteria = (self.recognisable, self.small_size, self.light_dark, self.distinctive)
        if self.kind == "icon" and any(value is not True for value in criteria):
            raise ValueError("icon approval requires every icon review criterion")
        if self.kind == "screenshot" and any(value is not None for value in criteria):
            raise ValueError("screenshot approval cannot assert icon-only review criteria")
        return self


class PluginPresentationCopyApproval(_PresentationModel):
    """Supplied copy-accuracy assertion for the exact selected settings object."""

    schema_version: Literal["plugin-presentation-copy-approval/v1"] = "plugin-presentation-copy-approval/v1"
    candidate: PackageCandidateIdentity
    openai_settings_sha256: Sha256
    accurate: Literal[True]
    evidence_ref: EvidenceRef
    evidence_sha256: Sha256


class PluginPresentationRequest(_PresentationModel):
    """Caller expectations and approvals for one fresh presentation assessment."""

    schema_version: Literal["plugin-presentation-request/v1"] = "plugin-presentation-request/v1"
    candidate: PackageCandidateIdentity
    mode_manifest_sha256: Sha256
    image_approvals: tuple[PluginImageApproval, ...] = Field(max_length=64)
    copy_approval: PluginPresentationCopyApproval

    @model_validator(mode="after")
    def approvals_bind_candidate(self) -> Self:
        paths = tuple(item.image_path for item in self.image_approvals)
        if len(paths) != len(set(paths)):
            raise ValueError("presentation image approval paths must be unique")
        if any(item.candidate != self.candidate for item in self.image_approvals):
            raise ValueError("every image approval must bind the requested candidate")
        if self.copy_approval.candidate != self.candidate:
            raise ValueError("copy approval must bind the requested candidate")
        return self


class PluginPresentationImage(_PresentationModel):
    """Decoded facts and supplied approval for one captured presentation image."""

    path: PortablePath
    sha256: Sha256
    size_bytes: int = Field(strict=True, ge=1, le=5 * 1024 * 1024)
    format: PresentationFormat
    width: float = Field(strict=True, gt=0, allow_inf_nan=False)
    height: float = Field(strict=True, gt=0, allow_inf_nan=False)
    roles: tuple[PresentationRole, ...] = Field(min_length=1, max_length=5)
    approval: PluginImageApproval

    @field_validator("path")
    @classmethod
    def portable_image_path(cls, value: str) -> str:
        require_portable_relative_path(value)
        return value

    @field_validator("roles")
    @classmethod
    def sorted_unique_roles(cls, value: tuple[PresentationRole, ...]) -> tuple[PresentationRole, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("presentation image roles must be sorted and unique")
        return value

    @model_validator(mode="after")
    def bind_approval_and_dimensions(self) -> Self:
        if self.path != self.approval.image_path or self.sha256 != self.approval.image_sha256:
            raise ValueError("presentation image must bind its exact approval path and digest")
        has_icon = any(role in _ICON_ROLES for role in self.roles)
        expected_kind = "icon" if has_icon else "screenshot"
        if self.approval.kind != expected_kind:
            raise ValueError("presentation image roles must match the approval kind")
        if has_icon:
            if self.width != self.height or self.width < 48:
                raise ValueError("icon images must be square and at least 48 by 48")
        elif self.width < 1 or self.height < 1:
            raise ValueError("screenshots must have positive dimensions")
        if "screenshot" in self.roles and self.format == "svg":
            raise ValueError("this profile supports raster screenshots only")
        if self.format != "svg" and (self.width > 4096 or self.height > 4096):
            raise ValueError("raster presentation dimensions cannot exceed 4096")
        return self


class PluginPresentationCheck(_PresentationModel):
    """Offline assessment of supplied assertions and freshly captured image bytes."""

    schema_version: Literal["plugin-presentation-check/v1"] = "plugin-presentation-check/v1"
    profile: Literal["openai-icons-2026-10-08/v1"] = "openai-icons-2026-10-08/v1"
    status: Literal["pass", "blocked"]
    candidate: PackageCandidateIdentity | None = None
    mode_manifest_sha256: Sha256 | None = None
    openai_settings_source: Literal["none", "inline", "compatibility"] = "none"
    openai_settings_sha256: Sha256 | None = None
    images: tuple[PluginPresentationImage, ...] = Field(default=(), max_length=64)
    copy_approval: PluginPresentationCopyApproval | None = None
    findings: tuple[SkillPackageFinding, ...] = ()
    mutation_performed: Literal[False] = False
    execution_authorized: Literal[False] = False
    release_ready: Literal[False] = False
    archive_verified: Literal[False] = False
    host_display_observed: Literal[False] = False
    publication_verified: Literal[False] = False

    @field_validator("images")
    @classmethod
    def sorted_unique_images(cls, value: tuple[PluginPresentationImage, ...]) -> tuple[PluginPresentationImage, ...]:
        paths = tuple(item.path for item in value)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("presentation images must have sorted unique paths")
        return value

    @model_validator(mode="after")
    def bind_assessment(self) -> Self:
        blockers = any(item.severity is ValidationSeverity.BLOCKER for item in self.findings)
        if (self.status == "blocked") != blockers:
            raise ValueError("presentation status must agree with blocker findings")
        if (self.candidate is None) != (self.mode_manifest_sha256 is None):
            raise ValueError("presentation candidate and mode digest must be present together")
        if (self.openai_settings_source == "none") != (self.openai_settings_sha256 is None):
            raise ValueError("selected settings source must agree with its digest")
        if self.candidate is None:
            if self.status == "pass":
                raise ValueError("passing presentation checks require an observed candidate")
            if self.images or self.copy_approval is not None or self.openai_settings_source != "none":
                raise ValueError("unbound presentation checks cannot retain candidate observations")
            return self
        if any(item.approval.candidate != self.candidate for item in self.images):
            raise ValueError("every presentation image approval must bind the assessed candidate")
        if self.copy_approval is not None and self.copy_approval.candidate != self.candidate:
            raise ValueError("copy approval must bind the assessed candidate")
        if self.copy_approval is not None and self.copy_approval.openai_settings_sha256 != self.openai_settings_sha256:
            raise ValueError("copy approval must bind the selected settings digest")
        if self.status == "pass":
            if self.openai_settings_source == "none" or self.copy_approval is None:
                raise ValueError("passing presentation checks require selected settings and copy approval")
            roles = {role for image in self.images for role in image.roles}
            if not {"logo", "composerIcon"}.issubset(roles):
                raise ValueError("passing presentation checks require logo and composerIcon")
        icon_roles = [role for image in self.images for role in image.roles if role in _ICON_ROLES]
        if len(icon_roles) != len(set(icon_roles)):
            raise ValueError("each declared icon role must name exactly one image")
        return self


_PRESENTATION_MODELS = frozenset(
    {
        PluginImageApproval,
        PluginPresentationCopyApproval,
        PluginPresentationRequest,
        PluginPresentationImage,
        PluginPresentationCheck,
        PackageCandidateIdentity,
        SkillPackageFinding,
    }
)


__all__ = [
    "PluginImageApproval",
    "PluginPresentationCheck",
    "PluginPresentationCopyApproval",
    "PluginPresentationImage",
    "PluginPresentationRequest",
]
