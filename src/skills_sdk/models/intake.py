"""Executable package intake and normalization contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import GitRevision, NonEmptyText, PortablePath, _ContractModel
from skills_sdk.models.package import (
    IntakeChecks,
    IntakeDecision,
    IntakeDecisionStatus,
    NormalizedPackage,
    PackageCandidateIdentity,
    PackageOwner,
    PackageSource,
    PackageSourceKind,
)
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.validation import SkillPackageValidation, ValidationSeverity

_CHECK_BLOCKERS = {
    "identity": "identity_unconfirmed",
    "provenance": "provenance_unconfirmed",
    "rights": "rights_unconfirmed",
    "owner_unchanged": "owner_decision_required",
}


def build_intake_decision(
    candidate: PackageCandidateIdentity,
    checks: IntakeChecks,
    *,
    additional_blocker_codes: tuple[str, ...] = (),
) -> IntakeDecision:
    """Project an intake decision deterministically from its persisted evidence."""

    check_blockers = tuple(code for field, code in _CHECK_BLOCKERS.items() if not getattr(checks, field))
    blocker_codes = tuple(dict.fromkeys((*additional_blocker_codes, *check_blockers)))
    if not (checks.identity and checks.provenance and checks.rights):
        status = IntakeDecisionStatus.BLOCK
    elif not checks.owner_unchanged:
        status = IntakeDecisionStatus.NEEDS_OWNER_DECISION
    else:
        status = IntakeDecisionStatus.ADMIT
    return IntakeDecision(candidate=candidate, decision=status, checks=checks, blocker_codes=blocker_codes)


class SkillPackageIntakeContext(_ContractModel):
    """Caller-supplied source and admission evidence for portable intake."""

    schema_version: Literal["skill-package-intake-context/v1"] = "skill-package-intake-context/v1"
    source_repository: NonEmptyText
    source_revision: GitRevision
    source_path: PortablePath
    source_kind: Literal[PackageSourceKind.GIT, PackageSourceKind.EXTERNAL, PackageSourceKind.LOCAL]
    owner: PackageOwner
    checks: IntakeChecks

    @field_validator("source_path")
    @classmethod
    def source_path_must_be_portable(cls, value: str) -> str:
        require_portable_relative_path(value)
        return value


class SkillPackageIntakeReceipt(_ContractModel):
    """Read-only structural intake and normalization result for one skill."""

    schema_version: Literal["skill-package-intake/v1"] = "skill-package-intake/v1"
    status: Literal["normalized", "blocked"]
    context: SkillPackageIntakeContext
    candidate: PackageCandidateIdentity | None = None
    validation: SkillPackageValidation
    source: PackageSource | None = None
    decision: IntakeDecision | None = None
    normalized_package: NormalizedPackage | None = None
    blocker: PackageReceiptBlocker | None = None
    mutation_performed: Literal[False] = False
    network_used: Literal[False] = False
    execution_performed: Literal[False] = False

    @model_validator(mode="after")
    def proof_is_candidate_bound(self) -> SkillPackageIntakeReceipt:
        if self.candidate != self.validation.candidate:
            raise ValueError("intake receipt candidate must match validation")
        if self.candidate is not None and self.context.source_revision != self.candidate.source_revision:
            raise ValueError("intake context revision must match the candidate")
        if self.status == "normalized":
            if self.validation.status != "pass":
                raise ValueError("normalized intake requires passing validation")
            if None in (self.candidate, self.source, self.decision, self.normalized_package):
                raise ValueError("normalized intake requires complete source, decision, and package proof")
            if self.blocker is not None:
                raise ValueError("normalized intake cannot contain a blocker")
            assert self.candidate is not None
            assert self.source is not None
            assert self.decision is not None
            assert self.normalized_package is not None
            if self.source.package_id != self.candidate.package_id:
                raise ValueError("intake source must bind the candidate package")
            if self.source.provenance.revision != self.candidate.source_revision:
                raise ValueError("intake source revision must bind the candidate")
            if self.source.provenance.content_sha256 != self.candidate.content_sha256:
                raise ValueError("intake source digest must bind the candidate")
            if self.source.provenance.repository != self.context.source_repository:
                raise ValueError("intake source repository must match the context")
            if self.source.provenance.path != self.context.source_path:
                raise ValueError("intake source path must match the context")
            if self.source.source_kind != self.context.source_kind:
                raise ValueError("intake source kind must match the context")
            if self.decision.candidate != self.candidate:
                raise ValueError("intake decision must bind the candidate")
            if self.decision.checks != self.context.checks:
                raise ValueError("intake decision checks must match the context")
            if self.decision != build_intake_decision(self.candidate, self.context.checks):
                raise ValueError("intake decision must match its persisted checks")
            if self.normalized_package.source != self.source:
                raise ValueError("normalized package must retain the intake source")
            if self.normalized_package.identity != self.validation.identity:
                raise ValueError("normalized package identity must match validation")
            if self.normalized_package.owner != self.context.owner:
                raise ValueError("normalized package owner must match the context")
        else:
            primary = next(
                (finding for finding in self.validation.findings if finding.severity is ValidationSeverity.BLOCKER),
                None,
            )
            if primary is None:
                raise ValueError("blocked intake requires a validation blocker")
            expected_blocker = PackageReceiptBlocker(
                code=primary.code,
                message=primary.message,
                evidence_refs=primary.evidence_refs,
            )
            if self.blocker != expected_blocker:
                raise ValueError("intake blocker must match the primary validation blocker")
            if self.blocker is None:
                raise ValueError("blocked intake requires a blocker")
            if self.normalized_package is not None or self.source is not None:
                raise ValueError("blocked intake cannot claim normalized package proof")
            if self.decision is not None and self.decision.decision is IntakeDecisionStatus.ADMIT:
                raise ValueError("blocked intake cannot contain an admit decision")
            if self.decision is not None:
                if self.decision.candidate != self.candidate:
                    raise ValueError("blocked intake decision must bind the candidate")
                expected_checks = self.context.checks.model_copy(update={"identity": False})
                if self.decision.checks != expected_checks:
                    raise ValueError("blocked intake decision must preserve context checks with failed identity")
                expected_decision = build_intake_decision(
                    self.candidate,
                    expected_checks,
                    additional_blocker_codes=(primary.code,),
                )
                if self.decision != expected_decision:
                    raise ValueError("blocked intake decision must match its persisted evidence")
        return self


__all__ = ["SkillPackageIntakeContext", "SkillPackageIntakeReceipt", "build_intake_decision"]
