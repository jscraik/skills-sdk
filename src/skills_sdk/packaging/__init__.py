"""Portable immutable package construction."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from skills_sdk.models.packaging import (
    PackageArchiveVerificationPolicy,
    PackageArchiveVerificationReceipt,
    PackageHardeningPolicy,
    PackageHardeningReceipt,
    PackageReceipt,
    PackageReceiptV2,
)
from skills_sdk.models.plugin_build import PluginBuildReceipt, PluginHardeningPolicy, PluginHardeningReceipt
from skills_sdk.models.plugin_presentation import PluginPresentationRequest

if TYPE_CHECKING:
    from skills_sdk.validation import SkillValidationPolicy


def build_skill_package(
    package_root: Path,
    *,
    source_revision: str,
    policy: SkillValidationPolicy | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PackageReceiptV2:
    """Load the manifest builder lazily to keep validation imports acyclic."""

    from skills_sdk.packaging.manifest import build_skill_package as _build_skill_package

    return _build_skill_package(
        package_root,
        source_revision=source_revision,
        policy=policy,
        clock=clock,
    )


def harden_skill_package(
    package_receipt: PackageReceipt | PackageReceiptV2,
    *,
    policy: PackageHardeningPolicy | None = None,
) -> PackageHardeningReceipt:
    """Load package hardening lazily to preserve the public import boundary."""

    from skills_sdk.packaging.hardening import harden_skill_package as _harden_skill_package

    return _harden_skill_package(package_receipt, policy=policy)


def verify_package_archive(
    archive_path: Path,
    *,
    expected_archive_sha256: str | None = None,
    expected_package_receipt: PackageReceiptV2 | None = None,
    policy: PackageArchiveVerificationPolicy | None = None,
) -> PackageArchiveVerificationReceipt:
    """Load archive verification lazily to preserve import boundaries."""

    from skills_sdk.packaging.archive_verification import verify_package_archive as _verify

    return _verify(
        archive_path,
        expected_archive_sha256=expected_archive_sha256,
        expected_package_receipt=expected_package_receipt,
        policy=policy,
    )


def build_plugin_package(plugin_root: Path, *, source_revision: str) -> PluginBuildReceipt:
    """Build a local whole-plugin receipt without emitting files."""
    from skills_sdk.packaging.plugin import build_plugin_package as _build

    return _build(plugin_root, source_revision=source_revision)


def harden_plugin_package(
    plugin_root: Path,
    build_receipt: PluginBuildReceipt,
    *,
    presentation_request: PluginPresentationRequest | None = None,
    policy: PluginHardeningPolicy | None = None,
) -> PluginHardeningReceipt:
    """Check fresh whole-plugin source and supplied presentation approvals locally."""
    from skills_sdk.packaging.plugin import harden_plugin_package as _harden

    return _harden(plugin_root, build_receipt, presentation_request=presentation_request, policy=policy)


__all__ = [
    "build_plugin_package",
    "build_skill_package",
    "harden_plugin_package",
    "harden_skill_package",
    "verify_package_archive",
]
