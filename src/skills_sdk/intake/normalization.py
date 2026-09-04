"""Read-only standalone-skill intake and normalization."""

from __future__ import annotations

from pathlib import Path

from skills_sdk.models.intake import SkillPackageIntakeContext, SkillPackageIntakeReceipt, build_intake_decision
from skills_sdk.models.package import (
    NormalizedPackage,
    PackageLifecycleState,
    PackageSource,
)
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.validation import ValidationSeverity
from skills_sdk.validation import SkillValidationPolicy, validate_skill_package


def intake_skill_package(
    package_root: Path,
    context: SkillPackageIntakeContext,
    *,
    policy: SkillValidationPolicy | None = None,
) -> SkillPackageIntakeReceipt:
    """Validate and normalize one package without copying, executing, or admitting it."""

    context = SkillPackageIntakeContext.model_validate(context.model_dump(mode="python"))
    validation = validate_skill_package(package_root, source_revision=context.source_revision, policy=policy)
    if validation.status == "blocked":
        first = next(finding for finding in validation.findings if finding.severity is ValidationSeverity.BLOCKER)
        decision = None
        if validation.candidate is not None:
            decision = build_intake_decision(
                validation.candidate,
                context.checks,
                additional_blocker_codes=(first.code,),
            )
        return SkillPackageIntakeReceipt(
            status="blocked",
            context=context,
            candidate=validation.candidate,
            validation=validation,
            decision=decision,
            blocker=PackageReceiptBlocker(
                code=first.code,
                message=first.message,
                evidence_refs=first.evidence_refs,
            ),
        )
    assert validation.candidate is not None
    assert validation.identity is not None
    source = PackageSource(
        package_id=validation.candidate.package_id,
        provenance={
            "repository": context.source_repository,
            "revision": validation.candidate.source_revision,
            "path": context.source_path,
            "content_sha256": validation.candidate.content_sha256,
        },
        source_kind=context.source_kind,
    )
    decision = build_intake_decision(validation.candidate, context.checks)
    normalized = NormalizedPackage(
        package_type="skill",
        identity=validation.identity,
        source=source,
        owner=context.owner,
        lifecycle=PackageLifecycleState.NORMALIZED,
    )
    return SkillPackageIntakeReceipt(
        status="normalized",
        context=context,
        candidate=validation.candidate,
        validation=validation,
        source=source,
        decision=decision,
        normalized_package=normalized,
    )


__all__ = ["intake_skill_package"]
