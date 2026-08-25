"""Portable package manifest and candidate-bound build receipt contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity


class PackageFileRole(StrEnum):
    """The portable role of a file included in a package manifest."""

    SKILL_MD = "skill_md"
    README = "readme"
    REFERENCE = "reference"
    SCRIPT = "script"
    ASSET = "asset"
    EVAL = "eval"


class PackageManifestFile(_ContractModel):
    """One immutable file entry in a package manifest."""

    path: PortablePath
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    role: PackageFileRole

    @field_validator("path")
    @classmethod
    def path_must_be_portable(cls, value: str) -> str:
        require_portable_relative_path(value)
        return value


class PackageManifestProvenance(_ContractModel):
    """Portable provenance references used to build a package manifest."""

    source: tuple[PortablePath, ...] = Field(min_length=1)
    builder: NonEmptyText

    @field_validator("source")
    @classmethod
    def sources_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            require_portable_relative_path(value)
        return values


class PackageManifest(_ContractModel):
    """Candidate-bound package contents before distribution or installation."""

    schema_version: Literal["package-manifest/v1"] = "package-manifest/v1"
    candidate: PackageCandidateIdentity
    version: NonEmptyText
    files: tuple[PackageManifestFile, ...] = Field(min_length=1)
    provenance: PackageManifestProvenance

    @model_validator(mode="after")
    def file_paths_are_unique(self) -> PackageManifest:
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("package manifest paths must be unique")
        return self


class PackageReceipt(_ContractModel):
    """Candidate-bound package result with explicit blocked outcomes."""

    schema_version: Literal["package-receipt/v1"] = "package-receipt/v1"
    candidate: PackageCandidateIdentity
    status: Literal["built", "blocked"]
    package_digest: Sha256
    manifest: PackageManifest
    included_files: tuple[PortablePath, ...] = ()
    excluded_files: tuple[PortablePath, ...] = ()
    blocker_codes: tuple[NonEmptyText, ...] = ()
    mutation_performed: Literal[False] = False

    @field_validator("included_files", "excluded_files")
    @classmethod
    def receipt_paths_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            require_portable_relative_path(value)
        return values

    @model_validator(mode="after")
    def receipt_matches_manifest(self) -> PackageReceipt:
        if self.manifest.candidate != self.candidate:
            raise ValueError("package receipt and manifest must bind the same candidate")
        manifest_paths = {item.path for item in self.manifest.files}
        included_paths = set(self.included_files)
        if self.status == "built":
            if not included_paths or included_paths != manifest_paths:
                raise ValueError("built package receipt must include every manifest path")
            if self.blocker_codes:
                raise ValueError("built package receipt cannot contain blockers")
        elif not self.blocker_codes:
            raise ValueError("blocked package receipt requires blocker_codes")
        if included_paths & set(self.excluded_files):
            raise ValueError("included and excluded package paths must be disjoint")
        return self


__all__ = [
    "PackageFileRole",
    "PackageManifest",
    "PackageManifestFile",
    "PackageManifestProvenance",
    "PackageReceipt",
]
