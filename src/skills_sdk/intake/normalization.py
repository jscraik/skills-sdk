"""Read-only standalone-skill intake and normalization."""

from __future__ import annotations

from pathlib import Path

from skills_sdk.models.intake import (
    SkillPackageIntakeContext,
    SkillPackageIntakeContextV2,
    SkillPackageIntakeContextV3,
    SkillPackageIntakeReceipt,
    SkillPackageIntakeReceiptV2,
    SkillPackageIntakeReceiptV3,
    build_intake_decision,
)
from skills_sdk.models.package import (
    ArchivePackageSource,
    NormalizedPackage,
    NormalizedPackageV2,
    NormalizedPackageV3,
    PackageLifecycleState,
    PackageSource,
    SavedReleasePackageSource,
)
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.validation import SkillPackageFinding, SkillPackageValidation, ValidationSeverity
from skills_sdk.validation import SkillValidationPolicy, validate_skill_package


def intake_skill_package(
    package_root: Path,
    context: SkillPackageIntakeContext | SkillPackageIntakeContextV2,
    *,
    policy: SkillValidationPolicy | None = None,
) -> SkillPackageIntakeReceipt | SkillPackageIntakeReceiptV2:
    """Validate and normalize one package without copying, executing, or admitting it."""

    archive = type(context) is SkillPackageIntakeContextV3 or (
        type(context) is dict and context.get("schema_version") == "skill-package-intake-context/v3"
    )
    saved = (
        archive
        or type(context) is SkillPackageIntakeContextV2
        or (type(context) is dict and context.get("schema_version") == "skill-package-intake-context/v2")
    )
    context_model = (
        SkillPackageIntakeContextV3
        if archive
        else (SkillPackageIntakeContextV2 if saved else SkillPackageIntakeContext)
    )
    context = context_model.model_validate(dict(context))
    receipt_model = (
        SkillPackageIntakeReceiptV3
        if archive
        else (SkillPackageIntakeReceiptV2 if saved else SkillPackageIntakeReceipt)
    )
    validation = validate_skill_package(package_root, source_revision=context.source_revision, policy=policy)
    if saved and validation.status == "pass" and validation.candidate != context.source.candidate:
        validation = SkillPackageValidation.model_validate(
            {
                **validation.model_dump(mode="json"),
                "status": "blocked",
                "findings": [
                    SkillPackageFinding(
                        code="saved_source_candidate_mismatch",
                        severity=ValidationSeverity.BLOCKER,
                        message=(
                            "Archive-source provenance does not bind the freshly captured child."
                            if archive
                            else "Saved-release provenance does not bind the freshly captured child."
                        ),
                    ).model_dump(mode="json")
                ],
            }
        )
    if validation.status == "blocked":
        first = next(finding for finding in validation.findings if finding.severity is ValidationSeverity.BLOCKER)
        decision = None
        if validation.candidate is not None:
            decision = build_intake_decision(
                validation.candidate,
                context.checks,
                additional_blocker_codes=(first.code,),
            )
        return receipt_model(
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
    source = (
        (ArchivePackageSource if archive else SavedReleasePackageSource)(
            package_id=validation.candidate.package_id, provenance=context.source
        )
        if saved
        else PackageSource(
            package_id=validation.candidate.package_id,
            provenance={
                "repository": context.source_repository,
                "revision": validation.candidate.source_revision,
                "path": context.source_path,
                "content_sha256": validation.candidate.content_sha256,
            },
            source_kind=context.source_kind,
        )
    )
    decision = build_intake_decision(validation.candidate, context.checks)
    normalized_model = NormalizedPackageV3 if archive else (NormalizedPackageV2 if saved else NormalizedPackage)
    normalized = normalized_model(
        package_type="skill",
        identity=validation.identity,
        source=source,
        owner=context.owner,
        lifecycle=PackageLifecycleState.NORMALIZED,
    )
    return receipt_model(
        status="normalized",
        context=context,
        candidate=validation.candidate,
        validation=validation,
        source=source,
        decision=decision,
        normalized_package=normalized,
    )


__all__ = ["intake_skill_package"]
