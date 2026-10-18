"""Read-only whole-plugin composition of accepted quality and presentation services."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from skills_sdk.evaluation.quality_workflow import check_local_quality
from skills_sdk.models.plugin import PluginValidationPolicy
from skills_sdk.models.plugin_quality import PluginQualityRequest, PluginQualityResult, supported_quality_root
from skills_sdk.models.quality_workflow import LocalCheckResultV2
from skills_sdk.validation.plugin_package import validate_plugin_package
from skills_sdk.validation.plugin_presentation import check_plugin_presentation


def _block(code: str, **evidence: object) -> PluginQualityResult:
    """Retain portable first-stop evidence without host paths or private exceptions."""
    return PluginQualityResult.model_validate(
        {
            **evidence,
            "status": "blocked",
            "blocker": {
                "code": code,
                "message": "Whole-plugin quality stopped; inspect retained evidence and correct the named gate.",
            },
        }
    )


async def check_plugin_quality(
    plugin_root: Path,
    request: object,
    *,
    assessments: Mapping[str, object] | None = None,
    presentation_request: object = None,
) -> PluginQualityResult:
    """Compose fresh root/child checks; supplied approvals do not become independent proof.

    This bounded route supports skill-only create/external-check candidates.
    Updates and MCP transport assessment require separate orchestration.
    """
    try:
        selected = PluginQualityRequest.model_validate(request)
    except (ValueError, TypeError, RecursionError):
        return _block("plugin_quality_request_invalid")
    capture = validate_plugin_package(
        plugin_root,
        source_revision=selected.candidate.source_revision,
        policy=PluginValidationPolicy(require_version=True, require_description=True),
    )
    evidence: dict[str, object] = {"request": selected, "initial_capture": capture}
    if not supported_quality_root(selected, capture):
        return _block("plugin_quality_root_mismatch", **evidence)
    supplied = assessments if assessments is not None else {}
    if type(supplied) is not dict or not set(supplied).issubset(child.path for child in selected.children):
        return _block("plugin_quality_assessments_invalid", **evidence)
    children: list[LocalCheckResultV2] = []
    for child in selected.children:
        result = await check_local_quality(plugin_root / child.path, child.request, assessment=supplied.get(child.path))
        children.append(result)
        evidence["children"] = tuple(children)
        if result.status != "local_checks_passed":
            return _block("plugin_quality_child_blocked", **evidence)
    if presentation_request is None:
        return _block("plugin_quality_presentation_missing", **evidence)
    presentation = check_plugin_presentation(
        plugin_root, request=presentation_request, source_revision=selected.candidate.source_revision
    )
    evidence["presentation"] = presentation
    if presentation.status != "pass" or (
        presentation.candidate != selected.candidate
        or presentation.mode_manifest_sha256 != selected.mode_manifest_sha256
    ):
        return _block("plugin_quality_presentation_blocked", **evidence)
    final = validate_plugin_package(
        plugin_root, source_revision=selected.candidate.source_revision, policy=capture.policy
    )
    evidence["final_capture"] = final
    if final != capture:
        return _block("plugin_quality_source_changed", **evidence)
    return PluginQualityResult.model_validate({**evidence, "status": "local_checks_passed"})


__all__ = ["check_plugin_quality"]
