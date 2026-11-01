"""Read-only whole-plugin composition of accepted quality and presentation services."""

from __future__ import annotations

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from pathlib import Path

from skills_sdk.evaluation.quality_workflow import check_local_quality
from skills_sdk.models.content_review import ContentReviewAssessment
from skills_sdk.models.plugin import PluginPackageValidation, PluginValidationPolicy
from skills_sdk.models.plugin_quality import (
    PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES,
    PLUGIN_QUALITY_REQUEST_MAX_BYTES,
    PluginQualityRequest,
    PluginQualityRequestV2,
    PluginQualityRequestV3,
    PluginQualityResult,
    PluginQualityResultV2,
    PluginQualityResultV3,
    _capture_metadata_is_safe,
    _child_metadata_is_safe,
    _presentation_metadata_is_safe,
    _public_envelope_is_safe,
    bounded_json_size,
    supported_quality_root,
)
from skills_sdk.models.quality_workflow import LocalCheckResultV2
from skills_sdk.models.validation import SkillPackageFinding, ValidationSeverity
from skills_sdk.validation.plugin_package import validate_plugin_package
from skills_sdk.validation.plugin_presentation import check_plugin_presentation


@dataclass
class _WorkerState:
    """Own the process-local executor and its matching admission capacity."""

    slots: threading.BoundedSemaphore = field(default_factory=lambda: threading.BoundedSemaphore(2))
    executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=2, thread_name_prefix="plugin-quality")
    )


_WORK_STATE = _WorkerState()


def _reset_workers_after_fork() -> None:
    """Replace inherited thread references and admission state in the forked child."""
    fresh = _WorkerState()
    _WORK_STATE.slots = fresh.slots
    _WORK_STATE.executor = fresh.executor


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_workers_after_fork)


def _assessments_within_budget(supplied: object, selected: PluginQualityRequest) -> bool:
    """Accept only a concrete dict of requested children within the aggregate evidence budget.

    The complete mapping, including paths and separators, is measured through
    bounded, container-limited compact JSON encoding so that no oversized or
    cyclic evidence is retained or revalidated.
    """
    if type(supplied) is not dict or len(supplied) > len(selected.children):
        return False
    selected_paths = {child.path for child in selected.children}
    if any(path not in selected_paths for path in supplied):
        return False
    try:
        bounded_json_size(supplied, PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES)
        normalized: dict[str, object] = {}
        for path, value in supplied.items():
            try:
                if isinstance(value, ContentReviewAssessment):
                    if type(value) is not ContentReviewAssessment:
                        continue
                    value = value.model_dump(mode="python", warnings="error")
                assessment = ContentReviewAssessment.model_validate(value)
            except (ValueError, TypeError, RecursionError):
                # Invalid individual evidence still stops in its existing child review stage.
                continue
            normalized[path] = assessment.model_dump(mode="json")
        bounded_json_size(normalized, PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES)
    except (ValueError, TypeError, RecursionError):
        return False
    return True


def _block(code: str, **evidence: object) -> PluginQualityResult:
    """Retain portable first-stop evidence without host paths or private exceptions."""
    envelope = {
        **evidence,
        "status": "blocked",
        "blocker": {
            "code": code,
            "message": "Whole-plugin quality stopped; inspect retained evidence and correct the named gate.",
        },
    }
    if evidence and not _public_envelope_is_safe(envelope):
        return _block("plugin_quality_input_invalid")
    try:
        model = (
            PluginQualityResultV3
            if isinstance(evidence.get("request"), PluginQualityRequestV3)
            else (
                PluginQualityResultV2
                if isinstance(evidence.get("request"), PluginQualityRequestV2)
                else PluginQualityResult
            )
        )
        return model.model_validate(envelope)
    except ValueError:
        if not evidence:
            raise
        return _block("plugin_quality_input_invalid")


async def _check_plugin_quality(
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
        if presentation_request is not None:
            bounded_json_size(presentation_request, PLUGIN_QUALITY_REQUEST_MAX_BYTES)
            if not _public_envelope_is_safe(presentation_request):
                return _block("plugin_quality_input_invalid")
        payload = PluginQualityRequest.canonical_inputs(request)
        model = (
            {
                "plugin-quality-request/v2": PluginQualityRequestV2,
                "plugin-quality-request/v3": PluginQualityRequestV3,
            }.get(payload.get("schema_version"), PluginQualityRequest)
            if isinstance(payload, dict)
            else PluginQualityRequest
        )
        selected = model.model_validate(payload)
    except (ValueError, TypeError, RecursionError):
        return _block("plugin_quality_request_invalid")
    capture = validate_plugin_package(
        plugin_root,
        source_revision=selected.candidate.source_revision,
        policy=PluginValidationPolicy(require_version=True, require_description=True),
    )
    if not _capture_metadata_is_safe(capture):
        return _block("plugin_quality_input_invalid")
    evidence: dict[str, object] = {"request": selected, "initial_capture": capture}
    if not supported_quality_root(selected, capture):
        return _block("plugin_quality_root_mismatch", **evidence)
    supplied = assessments if assessments is not None else {}
    if not _assessments_within_budget(supplied, selected):
        return _block("plugin_quality_assessments_invalid", **evidence)
    children: list[LocalCheckResultV2] = []
    for child in selected.children:
        result = await check_local_quality(plugin_root / child.path, child.request, assessment=supplied.get(child.path))
        if not _child_metadata_is_safe(result):
            return _block("plugin_quality_input_invalid")
        children.append(result)
        evidence["children"] = tuple(children)
        if result.status != "local_checks_passed":
            return _block("plugin_quality_child_blocked", **evidence)
    if presentation_request is None:
        return _block("plugin_quality_presentation_missing", **evidence)
    presentation = check_plugin_presentation(
        plugin_root, request=presentation_request, source_revision=selected.candidate.source_revision
    )
    if not _presentation_metadata_is_safe(presentation):
        return _block("plugin_quality_input_invalid")
    evidence["presentation"] = presentation
    if presentation.status != "pass" or (
        presentation.candidate != selected.candidate
        or presentation.mode_manifest_sha256 != selected.mode_manifest_sha256
    ):
        return _block("plugin_quality_presentation_blocked", **evidence)
    final = validate_plugin_package(
        plugin_root, source_revision=selected.candidate.source_revision, policy=capture.policy
    )
    if not _capture_metadata_is_safe(final):
        return _block("plugin_quality_input_invalid")
    if final.candidate is not None and (
        final.candidate.package_id != selected.candidate.package_id
        or final.candidate.source_revision != selected.candidate.source_revision
    ):
        final = PluginPackageValidation(
            status="blocked",
            policy=capture.policy,
            findings=(
                SkillPackageFinding(
                    code="plugin_quality_source_changed",
                    severity=ValidationSeverity.BLOCKER,
                    message="Final source capture no longer resolves the selected plugin identity.",
                    evidence_refs=("plugin.json",),
                ),
            ),
        )
    evidence["final_capture"] = final
    if final != capture:
        return _block("plugin_quality_source_changed", **evidence)
    envelope = {**evidence, "status": "local_checks_passed"}
    if not _public_envelope_is_safe(envelope):
        return _block("plugin_quality_input_invalid")
    try:
        model = (
            PluginQualityResultV3
            if isinstance(selected, PluginQualityRequestV3)
            else (PluginQualityResultV2 if isinstance(selected, PluginQualityRequestV2) else PluginQualityResult)
        )
        return model.model_validate(envelope)
    except ValueError:
        return _block("plugin_quality_input_invalid")


def _run_plugin_quality(
    plugin_root: Path, request: object, assessments: dict[str, object] | None, presentation_request: object
) -> PluginQualityResult:
    """Own the sequential supplied-only workflow and its event loop in one worker."""
    return asyncio.run(
        _check_plugin_quality(plugin_root, request, assessments=assessments, presentation_request=presentation_request)
    )


async def check_plugin_quality(
    plugin_root: Path,
    request: object,
    *,
    assessments: dict[str, object] | None = None,
    presentation_request: object = None,
) -> PluginQualityResult:
    """Compose read-only supplied checks without blocking the caller's event loop.

    At most two process-wide workers retain sequential first-stop semantics.
    Cancellation releases the caller; the bounded read-only worker may finish.
    The supplied-only profile admits no provider callbacks or release actions.
    """
    slots, executor = _WORK_STATE.slots, _WORK_STATE.executor
    if not slots.acquire(blocking=False):
        return _block("plugin_quality_capacity_exceeded")
    try:
        future = executor.submit(
            copy_context().run, _run_plugin_quality, plugin_root, request, assessments, presentation_request
        )
    except RuntimeError:
        slots.release()
        raise
    future.add_done_callback(lambda _completed: slots.release())
    return await asyncio.wrap_future(future)


__all__ = ["check_plugin_quality"]
