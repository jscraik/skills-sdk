"""Deterministic immutable manifest construction for validated skills."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.packaging import (
    PackageManifest,
    PackageManifestProvenance,
    PackageReceiptBlocker,
    PackageReceiptV2,
)
from skills_sdk.validation.skill_package import SkillValidationPolicy, validate_skill_package

Clock = Callable[[], datetime]


def _receipt_id(package_id: str, content_sha256: str) -> str:
    return f"{package_id}-{content_sha256[:16]}"


def _blocked_receipt_id(validation: object) -> str:
    return f"blocked-{canonical_json_sha256(validation)[:16]}"


def build_skill_package(
    package_root: Path,
    *,
    source_revision: str,
    policy: SkillValidationPolicy | None = None,
    clock: Clock | None = None,
) -> PackageReceiptV2:
    """Validate and build a candidate-bound, non-mutating package receipt."""

    active_clock = clock or (lambda: datetime.now(UTC))
    started_at = active_clock()
    validation = validate_skill_package(package_root, source_revision=source_revision, policy=policy)
    evidence = tuple(item.path for item in validation.files) or ("SKILL.md",)
    if validation.status == "blocked":
        first = validation.findings[0]
        candidate = validation.candidate
        return PackageReceiptV2(
            schema_version="package-receipt/v2",
            receipt_id=(
                _receipt_id(candidate.package_id, candidate.content_sha256)
                if candidate is not None
                else _blocked_receipt_id(validation.model_dump(mode="json"))
            ),
            candidate=candidate,
            lane="validation",
            status="blocked",
            started_at=started_at,
            finished_at=active_clock(),
            evidence=evidence,
            blocker=PackageReceiptBlocker(
                code=first.code,
                message=first.message,
                evidence_refs=first.evidence_refs,
            ),
            mutation_performed=False,
        )
    assert validation.candidate is not None
    assert validation.identity is not None
    manifest = PackageManifest(
        schema_version="package-manifest/v1",
        candidate=validation.candidate,
        version=validation.identity.version,
        files=validation.files,
        provenance=PackageManifestProvenance(source=("SKILL.md",), builder="skills-sdk.packaging.manifest/v1"),
    )
    package_digest = canonical_json_sha256(manifest.model_dump(mode="json"))
    return PackageReceiptV2(
        schema_version="package-receipt/v2",
        receipt_id=_receipt_id(validation.candidate.package_id, validation.candidate.content_sha256),
        candidate=validation.candidate,
        lane="validation",
        status="built",
        started_at=started_at,
        finished_at=active_clock(),
        evidence=evidence,
        package_digest=package_digest,
        manifest=manifest,
        included_files=evidence,
        mutation_performed=False,
    )


__all__ = ["build_skill_package"]
