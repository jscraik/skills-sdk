"""Portable standalone-skill validation contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity, SkillIdentity
from skills_sdk.models.packaging import BlockerCode, PackageManifestFile


class ValidationSeverity(StrEnum):
    """Whether a finding blocks immutable candidate construction."""

    WARNING = "warning"
    BLOCKER = "blocker"


class SkillPackageFinding(_ContractModel):
    """One stable, evidence-bound standalone-skill finding."""

    code: BlockerCode
    severity: ValidationSeverity
    message: NonEmptyText
    evidence_refs: tuple[PortablePath, ...] = ()

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            require_portable_relative_path(value)
        return values


class SkillPackageValidation(_ContractModel):
    """Read-only structural result for one standalone skill candidate."""

    schema_version: Literal["skill-package-validation/v1"] = "skill-package-validation/v1"
    candidate: PackageCandidateIdentity | None = None
    status: Literal["pass", "blocked"]
    identity: SkillIdentity | None = None
    files: tuple[PackageManifestFile, ...] = ()
    findings: tuple[SkillPackageFinding, ...] = ()
    mutation_performed: Literal[False] = False

    @model_validator(mode="after")
    def status_matches_findings(self) -> SkillPackageValidation:
        blockers = tuple(item for item in self.findings if item.severity is ValidationSeverity.BLOCKER)
        if self.status == "pass":
            if blockers:
                raise ValueError("passing skill validation cannot contain blockers")
            if self.candidate is None or self.identity is None or not self.files:
                raise ValueError("passing skill validation requires candidate, identity, and files")
            if self.identity.package_id != self.candidate.package_id:
                raise ValueError("skill validation identity must bind the same candidate package")
        elif not blockers:
            raise ValueError("blocked skill validation requires at least one blocker")
        paths = tuple(item.path for item in self.files)
        if len(paths) != len(set(paths)):
            raise ValueError("skill validation file paths must be unique")
        return self


__all__ = ["SkillPackageFinding", "SkillPackageValidation", "ValidationSeverity"]
