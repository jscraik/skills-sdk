"""Portable package manifest and candidate-bound build receipt contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity

ReceiptId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")]
BlockerCode = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]


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


class PackageReceiptBlocker(_ContractModel):
    """Stable typed blocker details for a package proof receipt."""

    code: BlockerCode
    message: NonEmptyText
    evidence_refs: tuple[PortablePath, ...] = ()

    @field_validator("evidence_refs")
    @classmethod
    def blocker_refs_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            require_portable_relative_path(value)
        return values


class PackageReceipt(_ContractModel):
    """Candidate-bound package result with stable proof-receipt fields."""

    schema_version: Literal["package-receipt/v1"] = "package-receipt/v1"
    receipt_id: ReceiptId
    candidate: PackageCandidateIdentity
    lane: Literal["validation"] = "validation"
    status: Literal["built", "blocked"]
    started_at: datetime
    finished_at: datetime
    evidence: tuple[PortablePath, ...] = Field(min_length=1)
    blocker: PackageReceiptBlocker | None = None
    package_digest: Sha256 | None = None
    manifest: PackageManifest | None = None
    included_files: tuple[PortablePath, ...] = ()
    excluded_files: tuple[PortablePath, ...] = ()
    mutation_performed: Literal[False] = False

    @field_validator("evidence", "included_files", "excluded_files")
    @classmethod
    def receipt_paths_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("package receipt paths must be unique")
        for value in values:
            require_portable_relative_path(value)
        return values

    @model_validator(mode="after")
    def receipt_matches_manifest(self) -> PackageReceipt:
        if self.finished_at < self.started_at:
            raise ValueError("package receipt finished_at must not precede started_at")
        if self.manifest is not None and self.manifest.candidate != self.candidate:
            raise ValueError("package receipt and manifest must bind the same candidate")
        manifest_paths = {item.path for item in self.manifest.files} if self.manifest is not None else set()
        included_paths = set(self.included_files)
        if self.status == "built":
            if self.package_digest is None or self.manifest is None:
                raise ValueError("built package receipt requires package_digest and manifest")
            if not included_paths or included_paths != manifest_paths:
                raise ValueError("built package receipt must include every manifest path")
            if self.blocker is not None:
                raise ValueError("built package receipt cannot contain a blocker")
        else:
            if self.blocker is None:
                raise ValueError("blocked package receipt requires a blocker")
            if self.package_digest is not None:
                raise ValueError("blocked package receipt cannot claim a package digest")
            if self.manifest is None and (self.included_files or self.excluded_files):
                raise ValueError("blocked receipt paths require a manifest")
            if not included_paths <= manifest_paths:
                raise ValueError("blocked package receipt included files must be manifested")
        if included_paths & set(self.excluded_files):
            raise ValueError("included and excluded package paths must be disjoint")
        return self


__all__ = [
    "PackageFileRole",
    "PackageManifest",
    "PackageManifestFile",
    "PackageManifestProvenance",
    "PackageReceipt",
    "PackageReceiptBlocker",
]
