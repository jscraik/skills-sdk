"""Verify retained plugin observations against fresh, safely captured source."""

from __future__ import annotations

from pathlib import Path

from skills_sdk.core.errors import ContractError
from skills_sdk.models.plugin import PluginPackageValidation, PluginValidationPolicy
from skills_sdk.validation.plugin_package import validate_plugin_package
from skills_sdk.validation.skill_package import _finding


def verify_plugin_package_validation(
    plugin_root: Path,
    validation: object,
    *,
    source_revision: str,
    policy: PluginValidationPolicy | None = None,
) -> PluginPackageValidation:
    """Recompute every observation without trusting supplied metadata or policy."""
    active = PluginValidationPolicy()
    code = "plugin_input_invalid"
    diagnostic = "plugin policy must contain only supported boolean requirements"
    try:
        active = PluginValidationPolicy.model_validate(policy if policy is not None else {})
        code = "plugin_evidence_invalid"
        diagnostic = "supplied plugin evidence must satisfy its bounded contract"
        supplied = PluginPackageValidation.model_validate(validation)
    except (ContractError, ValueError, TypeError, RecursionError):
        return PluginPackageValidation(
            status="blocked",
            policy=active,
            findings=(_finding(code, diagnostic),),
        )
    fresh = validate_plugin_package(plugin_root, source_revision=source_revision, policy=active)
    if fresh.status == "blocked":
        return fresh
    if fresh != supplied:
        return PluginPackageValidation(
            status="blocked",
            policy=active,
            findings=(
                _finding("plugin_evidence_mismatch", "supplied plugin evidence differs from fresh source validation"),
            ),
        )
    return fresh


__all__ = ["verify_plugin_package_validation"]
