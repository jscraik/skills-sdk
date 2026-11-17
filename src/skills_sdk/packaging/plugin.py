"""Read-only whole-plugin build and hardening; never emits an archive."""

from __future__ import annotations

from pathlib import Path

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.plugin import PluginValidationPolicy
from skills_sdk.models.plugin_build import (
    PluginBuildReceipt,
    PluginHardeningPolicy,
    PluginHardeningReceipt,
    plugin_hardening_blockers,
)
from skills_sdk.models.plugin_presentation import PluginPresentationRequest
from skills_sdk.validation.plugin_package import validate_plugin_package
from skills_sdk.validation.plugin_presentation import check_plugin_presentation


def build_plugin_package(plugin_root: Path, *, source_revision: str) -> PluginBuildReceipt:
    """Bind all captured plugin files, children and modes in a local build receipt."""
    capture = validate_plugin_package(
        plugin_root, source_revision=source_revision, policy=PluginValidationPolicy(require_version=True)
    )
    valid = capture.status == "pass"
    return PluginBuildReceipt(
        status="built" if valid else "blocked",
        validation=capture,
        build_digest=canonical_json_sha256(capture.model_dump(mode="json")) if valid else None,
    )


def harden_plugin_package(
    plugin_root: Path,
    build_receipt: PluginBuildReceipt,
    *,
    presentation_request: PluginPresentationRequest | None = None,
    policy: PluginHardeningPolicy | None = None,
) -> PluginHardeningReceipt:
    """Recapture source and check local policy plus exact supplied presentation approvals."""
    build = PluginBuildReceipt.model_validate(build_receipt)
    active = PluginHardeningPolicy.model_validate(policy if policy is not None else {})
    revision = build.validation.candidate.source_revision if build.validation.candidate is not None else "0" * 40
    fresh = validate_plugin_package(plugin_root, source_revision=revision, policy=build.validation.policy)
    presentation = (
        check_plugin_presentation(plugin_root, source_revision=revision, request=presentation_request)
        if presentation_request is not None
        else None
    )
    # Presentation inspection reads source too: recapture after it before joining evidence.
    final = validate_plugin_package(plugin_root, source_revision=revision, policy=build.validation.policy)
    stable = final == fresh
    blockers = plugin_hardening_blockers(build, final, presentation, active, stable)
    return PluginHardeningReceipt(
        status="blocked" if blockers else "pass",
        build=build,
        fresh_validation=final,
        presentation=presentation,
        policy=active,
        source_stable=stable,
        blockers=blockers,
    )
