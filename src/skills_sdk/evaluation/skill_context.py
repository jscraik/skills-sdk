"""Private, candidate-bound provider inputs captured without following symlinks."""

from __future__ import annotations

import json
from pathlib import PurePosixPath

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.evaluation.selected_case import SelectedCaseDefinition, _revalidate_definition
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.providers import DEFAULT_PROVIDER_CALL_LIMITS, JsonValue
from skills_sdk.validation.skill_package import SkillValidationPolicy, _scan_files

_EXCLUDED_REFERENCE_TERMS = ("eval", "scorer", "rubric", "calibration", "heldout", "held-out", "hidden")


def prepare_selected_case_context(
    definition: SelectedCaseDefinition, reference_paths: tuple[str, ...] = ()
) -> JsonValue:
    """Bind actual instructions and explicitly selected Markdown references.

    Raw source stays in private provider input, never a portable receipt. Known
    evaluation, scorer, rubric and calibration documents are excluded. Selection
    is explicit; this function does not claim all references are necessary.
    """
    validated = _revalidate_definition(definition)
    if (
        type(reference_paths) is not tuple
        or len(reference_paths) > 64
        or len(set(reference_paths)) != len(reference_paths)
    ):
        raise ValueError("skill context requires unique bounded reference selection")
    for path in reference_paths:
        require_portable_relative_path(path)
        parsed = PurePosixPath(path)
        if (
            parsed.parts[0] != "references"
            or parsed.suffix.casefold() not in {".md", ".markdown"}
            or any(term in part.casefold() for part in parsed.parts for term in _EXCLUDED_REFERENCE_TERMS)
        ):
            raise ValueError("skill context excludes hidden evaluation inputs")
    files, findings, captured = _scan_files(validated._package_root, SkillValidationPolicy())
    identity = validated.scenario_set.candidate
    if findings or candidate_content_sha256(files) != identity.content_sha256:
        raise ContractError(
            code="skill_context_source_changed", message="Skill context requires unchanged captured source."
        )
    paths = ("SKILL.md", *sorted(reference_paths))
    by_path = {item.path: item for item in files}
    try:
        documents = [
            {"path": path, "sha256": by_path[path].sha256, "text": captured[path].decode("utf-8")} for path in paths
        ]
    except (KeyError, UnicodeError):
        raise ValueError("skill context requires readable selected UTF-8 documents") from None
    payload = {
        "prompt": validated.scenario_set.cases[0].prompt,
        "skill_context": {"candidate": identity.model_dump(mode="json"), "documents": documents},
    }
    if (
        len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        > DEFAULT_PROVIDER_CALL_LIMITS.input_bytes
    ):
        raise ValueError("skill context exceeds the provider input budget")
    return payload


def _context_matches_definition(definition: SelectedCaseDefinition, payload: JsonValue) -> bool:
    if not isinstance(payload, dict) or set(payload) != {"prompt", "skill_context"}:
        return False
    context = payload.get("skill_context")
    if not isinstance(context, dict) or set(context) != {"candidate", "documents"}:
        return False
    documents = context.get("documents")
    if not isinstance(documents, list) or not documents or len(documents) > 65:
        return False
    if any(not isinstance(item, dict) or not isinstance(item.get("path"), str) for item in documents):
        return False
    paths = tuple(item["path"] for item in documents)
    if paths[0] != "SKILL.md":
        return False
    try:
        return payload == prepare_selected_case_context(definition, paths[1:])
    except (TypeError, ValueError, ContractError, OSError):
        return False


def _request_matches_context_or_prompt(
    definition: SelectedCaseDefinition, request: ProviderExecutionRequest, input_payload: JsonValue
) -> bool:
    case = definition.scenario_set.cases[0]
    input_matches = input_payload == {"prompt": case.prompt} or _context_matches_definition(definition, input_payload)
    return (
        request.candidate == definition.scenario_set.candidate
        and request.scenario_set_id == definition.scenario_set.scenario_set_id
        and request.case_id == case.case_id
        and input_matches
        and request.input_sha256 == canonical_json_sha256(input_payload)
    )
