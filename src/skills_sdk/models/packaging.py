"""Portable package manifest and candidate-bound build receipt contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
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

    schema_version: Literal["package-manifest/v1"]
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

    schema_version: Literal["package-receipt/v1"]
    receipt_id: ReceiptId
    candidate: PackageCandidateIdentity | None = None
    lane: Literal["validation"]
    status: Literal["built", "blocked"]
    started_at: AwareDatetime
    finished_at: AwareDatetime
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
            if self.candidate is None or self.package_digest is None or self.manifest is None:
                raise ValueError("built package receipt requires candidate, package_digest, and manifest")
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
            if set(self.excluded_files) & manifest_paths:
                raise ValueError("blocked package receipt excluded files must not be manifested")
        if included_paths & set(self.excluded_files):
            raise ValueError("included and excluded package paths must be disjoint")
        return self


class PackageReceiptV2(PackageReceipt):
    """Digest-bound package result that preserves the v1 receipt shape."""

    schema_version: Literal["package-receipt/v2"]

    @model_validator(mode="after")
    def package_digest_matches_manifest(self) -> PackageReceiptV2:
        if self.status == "built":
            assert self.manifest is not None
            assert self.candidate is not None
            expected_content_digest = candidate_content_sha256(self.manifest.files)
            if self.candidate.content_sha256 != expected_content_digest:
                raise ValueError("built package receipt candidate digest must match manifest files")
            expected_digest = canonical_json_sha256(self.manifest.model_dump(mode="json"))
            if self.package_digest != expected_digest:
                raise ValueError("built package receipt digest must match the canonical manifest")
        return self


class PackageHardeningPolicy(_ContractModel):
    """Portable, explicit package-hardening limits."""

    max_file_count: int = Field(default=250, ge=1)
    max_total_bytes: int = Field(default=5 * 1024 * 1024, ge=1)
    require_readme: bool = True


class PackageHardeningCheck(_ContractModel):
    """One deterministic hardening decision and its evidence."""

    id: BlockerCode
    status: Literal["pass", "warning", "blocker"]
    message: NonEmptyText
    evidence: tuple[NonEmptyText, ...] = ()


class PackageHardeningReceipt(_ContractModel):
    """Candidate-bound, non-mutating package hardening result."""

    schema_version: Literal["package-hardening/v1"] = "package-hardening/v1"
    candidate: PackageCandidateIdentity | None = None
    build_status: Literal["built", "blocked"]
    status: Literal["pass", "blocked"]
    package_digest: Sha256 | None = None
    effective_policy: PackageHardeningPolicy
    included_files: tuple[PortablePath, ...] = ()
    file_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)
    hardening_checks: tuple[PackageHardeningCheck, ...] = Field(min_length=1)
    blockers: tuple[PackageHardeningCheck, ...] = ()
    warnings: tuple[PackageHardeningCheck, ...] = ()
    mutation_performed: Literal[False] = False
    acceptance_trace: tuple[NonEmptyText, ...] = Field(min_length=1)

    @field_validator("included_files")
    @classmethod
    def included_paths_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("hardening receipt paths must be unique")
        for value in values:
            require_portable_relative_path(value)
        return values

    @model_validator(mode="after")
    def status_matches_checks(self) -> PackageHardeningReceipt:
        check_ids = tuple(item.id for item in self.hardening_checks)
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("hardening check ids must be unique")
        expected_blockers = tuple(item for item in self.hardening_checks if item.status == "blocker")
        expected_warnings = tuple(item for item in self.hardening_checks if item.status == "warning")
        if self.blockers != expected_blockers or self.warnings != expected_warnings:
            raise ValueError("hardening blocker and warning projections must match checks")
        if self.file_count != len(self.included_files):
            raise ValueError("hardening file_count must match included_files")
        if self.status == "pass":
            if expected_blockers:
                raise ValueError("passing hardening receipt cannot contain blockers")
            if self.build_status != "built" or self.candidate is None or self.package_digest is None:
                raise ValueError("passing hardening receipt requires a built candidate and package_digest")
        else:
            if not expected_blockers:
                raise ValueError("blocked hardening receipt requires a blocker")
            if self.build_status == "built":
                if self.candidate is None or self.package_digest is None:
                    raise ValueError("hardening-blocked built package must preserve candidate and package_digest")
            elif self.package_digest is not None:
                raise ValueError("build-blocked hardening receipt cannot claim a package digest")
        return self


__all__ = [
    "PackageFileRole",
    "PackageHardeningCheck",
    "PackageHardeningPolicy",
    "PackageHardeningReceipt",
    "PackageManifest",
    "PackageManifestFile",
    "PackageManifestProvenance",
    "PackageReceipt",
    "PackageReceiptBlocker",
    "PackageReceiptV2",
]
