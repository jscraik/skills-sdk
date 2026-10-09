"""Private whole-plugin context capture for matched case execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.evaluation.selected_case import SelectedCaseDefinition, _revalidate_definition
from skills_sdk.models.plugin import PluginPackageValidation, PluginSkillBinding, PluginValidationPolicy
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.providers import DEFAULT_PROVIDER_CALL_LIMITS, JsonValue
from skills_sdk.validation.plugin_capture import capture_plugin_source
from skills_sdk.validation.plugin_evidence import verify_plugin_package_validation

_EXCLUDED_REFERENCE_TERMS = ("eval", "scorer", "rubric", "calibration", "heldout", "held-out", "hidden")


@dataclass(frozen=True, slots=True)
class PluginExecutionContext:
    """Supply retained plugin evidence and an explicit bounded document selection."""

    root: Path
    validation: PluginPackageValidation
    driver_skill_path: str
    selected_skill_paths: tuple[str, ...]
    reference_paths: tuple[str, ...] = ()
    policy: PluginValidationPolicy | None = None
    safety_evidence: object = None


def _error(code: str, message: str) -> ContractError:
    """Create a stable private context error."""
    return ContractError(code=code, message=message)


def _validated_policy(context: PluginExecutionContext) -> PluginValidationPolicy:
    """Revalidate the independently supplied policy and bind it to retained evidence."""
    try:
        policy = PluginValidationPolicy.model_validate(context.policy if context.policy is not None else {})
    except (TypeError, ValueError, ContractError, RecursionError):
        raise _error("invalid_matched_plugin_context", "plugin context policy is invalid") from None
    if policy != context.validation.policy:
        raise _error("invalid_matched_plugin_context", "plugin context policy differs from retained evidence")
    return policy


def _validated_paths(context: PluginExecutionContext) -> tuple[str, ...]:
    """Validate selected child and reference paths without inspecting source."""
    selected = context.selected_skill_paths
    if (
        type(selected) is not tuple
        or not selected
        or len(selected) > 128
        or any(type(path) is not str for path in selected)
        or selected != tuple(sorted(set(selected)))
    ):
        raise _error("invalid_matched_plugin_context", "selected plugin skills must be sorted and unique")
    if type(context.driver_skill_path) is not str or context.driver_skill_path not in selected:
        raise _error("invalid_matched_plugin_context", "selected plugin skills must include the driver")
    references = context.reference_paths
    if (
        type(references) is not tuple
        or len(references) > 64
        or any(type(path) is not str for path in references)
        or references != tuple(sorted(set(references)))
    ):
        raise _error("invalid_matched_plugin_context", "plugin references must be sorted and unique")
    for path in (*selected, context.driver_skill_path, *references):
        try:
            require_portable_relative_path(path)
        except (TypeError, ValueError, ContractError):
            raise _error("invalid_matched_plugin_context", "plugin context paths must be portable") from None
    for path in references:
        parsed = PurePosixPath(path)
        if parsed.parts[0] == "skills" and "/".join(parsed.parts[:2]) not in selected:
            raise _error("invalid_matched_plugin_context", "plugin references within skills require a selected child")
        if parsed.suffix.casefold() not in {".md", ".markdown"} or any(
            term in part.casefold() for part in parsed.parts for term in _EXCLUDED_REFERENCE_TERMS
        ):
            raise _error("invalid_matched_plugin_context", "plugin context excludes hidden evaluation inputs")
    return references


def _selected_bindings(
    definition: SelectedCaseDefinition, context: PluginExecutionContext
) -> tuple[PluginSkillBinding, ...]:
    """Bind the selected driver definition to retained whole-plugin child identities."""
    by_path = {item.path: item for item in context.validation.skills}
    try:
        selected = tuple(by_path[path] for path in context.selected_skill_paths)
        driver = by_path[context.driver_skill_path]
    except KeyError:
        raise _error(
            "invalid_matched_plugin_context", "selected plugin skill is not present in retained evidence"
        ) from None
    if any(item.validation.status != "pass" or item.validation.candidate is None for item in selected):
        raise _error("invalid_matched_plugin_context", "selected plugin skills require passing child evidence")
    if driver.validation.candidate != definition.scenario_set.candidate:
        raise _error("invalid_matched_plugin_context", "driver definition does not bind the selected plugin child")
    if definition._package_root != context.root.absolute() / context.driver_skill_path:
        raise _error("invalid_matched_plugin_context", "driver package root does not bind the plugin root")
    return selected


def _require_fresh(context: PluginExecutionContext, policy: PluginValidationPolicy) -> None:
    """Require retained evidence to equal a fresh whole-plugin verification."""
    fresh = verify_plugin_package_validation(
        context.root,
        context.validation,
        source_revision=context.validation.candidate.source_revision if context.validation.candidate else "",
        policy=policy,
    )
    if fresh.status != "pass" or fresh != context.validation:
        raise _error("matched_plugin_source_changed", "plugin context requires unchanged verified source")


def _documents(context: PluginExecutionContext) -> list[JsonValue]:
    """Capture selected instructions and explicit Markdown references from plugin bytes."""
    try:
        files, payloads, _directories = capture_plugin_source(context.root)
    except (OSError, TypeError, ValueError, ContractError, RecursionError):
        raise _error("matched_plugin_source_changed", "plugin context source could not be captured") from None
    if files != context.validation.files:
        raise _error("matched_plugin_source_changed", "plugin source changed during context capture")
    selected_documents = tuple(f"{path}/SKILL.md" for path in context.selected_skill_paths)
    paths = (*selected_documents, *context.reference_paths)
    if len(paths) != len(set(paths)):
        raise _error("invalid_matched_plugin_context", "plugin context document selection must be unique")
    by_path = {item.path: item for item in files}
    try:
        return [
            {"path": path, "sha256": by_path[path].sha256, "text": payloads[path].decode("utf-8")} for path in paths
        ]
    except (KeyError, UnicodeError):
        raise _error("invalid_matched_plugin_context", "plugin context requires captured UTF-8 documents") from None


def prepare_matched_plugin_context(definition: SelectedCaseDefinition, context: PluginExecutionContext) -> JsonValue:
    """Prepare bounded generator input bound to fresh whole-plugin and child evidence."""
    if type(context) is not PluginExecutionContext or not isinstance(context.root, Path):
        raise _error("invalid_matched_plugin_context", "plugin execution context is invalid")
    validated = _revalidate_definition(definition)
    try:
        validation = PluginPackageValidation.model_validate(context.validation)
    except (TypeError, ValueError, ContractError, RecursionError):
        raise _error("invalid_matched_plugin_context", "plugin context evidence is invalid") from None
    if validation.status != "pass" or validation.candidate is None or validation.mode_manifest_sha256 is None:
        raise _error("invalid_matched_plugin_context", "plugin context requires passing bound evidence")
    if validation != context.validation:
        raise _error("invalid_matched_plugin_context", "plugin context evidence failed exact revalidation")
    context = PluginExecutionContext(
        root=context.root,
        validation=validation,
        driver_skill_path=context.driver_skill_path,
        selected_skill_paths=context.selected_skill_paths,
        reference_paths=context.reference_paths,
        policy=context.policy,
        safety_evidence=context.safety_evidence,
    )
    policy = _validated_policy(context)
    _validated_paths(context)
    selected = _selected_bindings(validated, context)
    _require_fresh(context, policy)
    documents = _documents(context)
    payload: JsonValue = {
        "prompt": validated.scenario_set.cases[0].prompt,
        "plugin_context": {
            "candidate": validation.candidate.model_dump(mode="json"),
            "mode_manifest_sha256": validation.mode_manifest_sha256,
            "driver_skill_path": context.driver_skill_path,
            "selected_skills": [
                {"path": item.path, "candidate": item.validation.candidate.model_dump(mode="json")} for item in selected
            ],
            "documents": documents,
        },
    }
    encoded_size = len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    if encoded_size > DEFAULT_PROVIDER_CALL_LIMITS.input_bytes:
        raise _error("invalid_matched_plugin_context", "plugin context exceeds the provider input budget")
    _require_fresh(context, policy)
    return payload


def _request_matches_plugin_context(
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    payload: JsonValue,
    context: PluginExecutionContext,
) -> bool:
    """Bind the actual child request without widening standalone selected-case inputs."""
    case = definition.scenario_set.cases[0]
    return (
        request.candidate == definition.scenario_set.candidate
        and request.scenario_set_id == definition.scenario_set.scenario_set_id
        and request.case_id == case.case_id
        and request.input_sha256 == canonical_json_sha256(payload)
        and payload == prepare_matched_plugin_context(definition, context)
    )


__all__ = ["PluginExecutionContext", "prepare_matched_plugin_context"]
