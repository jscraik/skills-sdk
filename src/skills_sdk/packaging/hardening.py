"""Deterministic package hardening over an immutable build receipt."""

from __future__ import annotations

from typing import Literal

from skills_sdk.core.package_safety import unsafe_package_path_reason
from skills_sdk.models.packaging import (
    PackageHardeningCheck,
    PackageHardeningPolicy,
    PackageHardeningReceipt,
    PackageManifestFile,
    PackageReceipt,
)

_ACCEPTANCE_TRACE = ("portable-package", "immutable-candidate", "non-mutating-hardening")
def _check(
    check_id: str,
    *,
    status: Literal["pass", "warning", "blocker"],
    message: str,
    evidence: tuple[str, ...] = (),
) -> PackageHardeningCheck:
    return PackageHardeningCheck(
        id=check_id,
        status=status,
        message=message,
        evidence=evidence,
    )


def _package_receipt_check(receipt: PackageReceipt) -> PackageHardeningCheck:
    return _check(
        "package_receipt_built",
        status="pass" if receipt.status == "built" else "blocker",
        message="Package hardening requires a successful immutable package receipt.",
        evidence=(f"package_receipt_status:{receipt.status}",),
    )


def _forbidden_paths_check(receipt: PackageReceipt) -> PackageHardeningCheck:
    forbidden = tuple(
        f"{path}:{reason}"
        for path in receipt.included_files
        if (reason := unsafe_package_path_reason(path)) is not None
    )
    return _check(
        "forbidden_package_paths",
        status="blocker" if forbidden else "pass",
        message="Package contents must exclude runtime, generated, dependency, and secret-bearing paths.",
        evidence=forbidden,
    )


def _size_budget_check(
    files: tuple[PackageManifestFile, ...], policy: PackageHardeningPolicy
) -> PackageHardeningCheck:
    total_size = sum(item.size_bytes for item in files)
    within_budget = len(files) <= policy.max_file_count and total_size <= policy.max_total_bytes
    return _check(
        "package_size_budget",
        status="pass" if within_budget else "warning",
        message="Package contents should remain within the explicit hardening budget.",
        evidence=(
            f"files:{len(files)}/{policy.max_file_count}",
            f"total_size_bytes:{total_size}/{policy.max_total_bytes}",
        ),
    )


def _provenance_check(receipt: PackageReceipt) -> PackageHardeningCheck:
    provenance = receipt.manifest.provenance if receipt.manifest is not None else None
    valid = bool(
        provenance is not None
        and provenance.builder == "skills-sdk.packaging.manifest/v1"
        and "SKILL.md" in provenance.source
    )
    evidence = () if provenance is None else (f"builder:{provenance.builder}", *provenance.source)
    return _check(
        "provenance_trace",
        status="pass" if valid else "blocker",
        message="Package hardening requires the Skills SDK manifest builder and SKILL.md source provenance.",
        evidence=evidence,
    )


def _required_role_check(
    files: tuple[PackageManifestFile, ...], policy: PackageHardeningPolicy
) -> PackageHardeningCheck:
    roles = tuple(sorted({item.role.value for item in files}))
    has_skill = "skill_md" in roles
    has_readme = any(item.role.value == "readme" and item.path == "README.md" for item in files)
    valid = has_skill and (has_readme or not policy.require_readme)
    return _check(
        "required_package_roles",
        status="pass" if valid else "blocker",
        message="Package manifest must include SKILL.md and, when required, root README.md roles.",
        evidence=roles,
    )


def harden_skill_package(
    package_receipt: PackageReceipt,
    *,
    policy: PackageHardeningPolicy | None = None,
) -> PackageHardeningReceipt:
    """Return a typed, read-only hardening decision for one build receipt."""

    active_policy = policy or PackageHardeningPolicy()
    manifest_files = package_receipt.manifest.files if package_receipt.manifest is not None else ()
    included_paths = set(package_receipt.included_files)
    files = tuple(item for item in manifest_files if item.path in included_paths)
    checks = (
        _package_receipt_check(package_receipt),
        _forbidden_paths_check(package_receipt),
        _size_budget_check(files, active_policy),
        _provenance_check(package_receipt),
        _required_role_check(files, active_policy),
    )
    blockers = tuple(item for item in checks if item.status == "blocker")
    warnings = tuple(item for item in checks if item.status == "warning")
    return PackageHardeningReceipt(
        candidate=package_receipt.candidate,
        build_status=package_receipt.status,
        status="blocked" if blockers else "pass",
        package_digest=package_receipt.package_digest,
        effective_policy=active_policy,
        included_files=package_receipt.included_files,
        file_count=len(files),
        total_size_bytes=sum(item.size_bytes for item in files),
        hardening_checks=checks,
        blockers=blockers,
        warnings=warnings,
        acceptance_trace=_ACCEPTANCE_TRACE,
    )


__all__ = ["harden_skill_package"]
