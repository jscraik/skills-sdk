"""Read-only whole-plugin composition of accepted quality and presentation services."""

from __future__ import annotations

import json
from pathlib import Path

from skills_sdk.evaluation.quality_workflow import check_local_quality
from skills_sdk.models.plugin import PluginValidationPolicy
from skills_sdk.models.plugin_quality import (
    PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES,
    PluginQualityRequest,
    PluginQualityResult,
    supported_quality_root,
)
from skills_sdk.models.quality_workflow import LocalCheckResultV2
from skills_sdk.validation.plugin_package import validate_plugin_package
from skills_sdk.validation.plugin_presentation import check_plugin_presentation


def _assessments_within_budget(supplied: object, selected: PluginQualityRequest) -> bool:
    """Accept only a concrete dict of requested children within the aggregate evidence budget.

    The complete mapping, including paths and separators, is measured through
    bounded, container-limited compact JSON encoding so that no oversized or
    cyclic evidence is retained or revalidated.
    """
    if type(supplied) is not dict or not set(supplied).issubset(child.path for child in selected.children):
        return False
    try:
        _bounded_size(supplied, PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES)
    except (ValueError, TypeError, RecursionError):
        return False
    return True


def _bounded_size(value: object, limit: int) -> int:
    """Measure compact UTF-8 JSON without allocating an aggregate encoded copy."""
    remaining = [limit]

    def consume(size: int) -> None:
        remaining[0] -= size
        if remaining[0] < 0:
            raise ValueError("supplied assessments exceed the aggregate evidence budget")

    def visit(item: object, depth: int) -> None:
        if depth > 64:
            raise ValueError("assessment nesting exceeds its bound")
        if type(item) is dict:
            consume(2 + max(0, len(item) - 1) + len(item))
            for key, member in item.items():
                if type(key) is not str:
                    raise ValueError("assessment evidence requires string keys")
                visit(key, depth + 1)
                visit(member, depth + 1)
        elif type(item) in (list, tuple):
            consume(2 + max(0, len(item) - 1))
            for member in item:
                visit(member, depth + 1)
        elif type(item) is str:
            consume(2)
            for start in range(0, len(item), 4096):
                consume(len(json.dumps(item[start : start + 4096], ensure_ascii=False).encode("utf-8")) - 2)
        elif item is None or type(item) in (int, float, bool):
            consume(len(json.dumps(item, allow_nan=False)))
        elif hasattr(item, "model_fields") and type(item).__module__.startswith("skills_sdk."):
            visit(item.__dict__, depth + 1)
        else:
            raise ValueError("assessment evidence requires canonical JSON values")

    visit(value, 0)
    return limit - remaining[0]


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
    assessments: dict[str, object] | None = None,
    presentation_request: object = None,
) -> PluginQualityResult:
    """Compose fresh root/child checks; supplied approvals do not become independent proof.

    `assessments` must be a concrete `dict` keyed by requested child path whose
    combined evidence stays within `PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES`;
    other mappings and oversized bundles return `plugin_quality_assessments_invalid`.
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
    if not _assessments_within_budget(supplied, selected):
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
