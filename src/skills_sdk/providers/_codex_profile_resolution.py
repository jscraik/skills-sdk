"""Resolve only explicitly supplied profile dependencies, never ambient state."""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import dataclass

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.providers._codex_profile import _parse_codex_profile, _ParsedCodexProfile, _providers, _text

_CATALOGUE_FIELDS = {
    "slug",
    "display_name",
    "description",
    "default_reasoning_level",
    "supported_reasoning_levels",
    "shell_type",
    "visibility",
    "supported_in_api",
    "priority",
    "upgrade",
    "base_instructions",
    "model_messages",
    "supports_reasoning_summaries",
    "default_reasoning_summary",
    "support_verbosity",
    "default_verbosity",
    "apply_patch_tool_type",
    "web_search_tool_type",
    "truncation_policy",
    "supports_parallel_tool_calls",
    "supports_image_detail_original",
    "context_window",
    "max_context_window",
    "experimental_supported_tools",
    "input_modalities",
    "service_tiers",
    "additional_speed_tiers",
    "availability_nux",
    "use_responses_lite",
    "supports_search_tool",
}

_CATALOGUE_BOOLEANS = {
    "supported_in_api",
    "supports_reasoning_summaries",
    "support_verbosity",
    "supports_parallel_tool_calls",
    "supports_image_detail_original",
    "use_responses_lite",
    "supports_search_tool",
}
_CATALOGUE_NUMBERS = {"priority", "context_window", "max_context_window"}
_CATALOGUE_ARRAYS = {
    "supported_reasoning_levels",
    "experimental_supported_tools",
    "input_modalities",
    "service_tiers",
    "additional_speed_tiers",
}
_CATALOGUE_OBJECTS = {"model_messages", "truncation_policy"}
_CATALOGUE_OPTIONAL = {"availability_nux", "upgrade"}


def _json_values_are_bounded(value: object) -> None:
    """Reject non-finite or excessively nested JSON before canonical hashing."""
    pending = [(value, 0)]
    remaining = 32768
    while pending:
        item, depth = pending.pop()
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise _dependency_error()
        if type(item) is dict:
            pending.extend((member, depth + 1) for pair in item.items() for member in pair)
        elif type(item) is list:
            pending.extend((member, depth + 1) for member in item)
        elif type(item) is float and not math.isfinite(item):
            raise _dependency_error()
        elif type(item) is str:
            try:
                item.encode("utf-8")
            except UnicodeError:
                raise _dependency_error() from None


def _validate_catalogue_entry(entry: object) -> None:
    """Check supported field shapes, not their use by a running Codex version."""
    if type(entry) is not dict or set(entry) - _CATALOGUE_FIELDS:
        raise _dependency_error()
    for key, value in entry.items():
        if key in _CATALOGUE_BOOLEANS:
            valid = type(value) is bool
        elif key in _CATALOGUE_NUMBERS:
            valid = type(value) is int and value >= (0 if key == "priority" else 1)
        elif key in _CATALOGUE_ARRAYS:
            valid = type(value) is list and len(value) <= 256
        elif key in _CATALOGUE_OBJECTS:
            valid = type(value) is dict
        elif key in _CATALOGUE_OPTIONAL:
            valid = value is None or type(value) is dict
        else:
            valid = type(value) is str
        if not valid:
            raise _dependency_error()
    if "supported_reasoning_levels" in entry:
        _reasoning_levels(entry["supported_reasoning_levels"])


def _reasoning_levels(value: object) -> tuple[str, ...]:
    """Read explicit advertised effort records; do not invent a global effort enum."""
    if type(value) is not list or not 1 <= len(value) <= 256:
        raise _dependency_error()
    efforts: list[str] = []
    for item in value:
        if (
            type(item) is not dict
            or set(item) != {"effort", "description"}
            or not _text(item["effort"])
            or not _text(item["description"])
            or item["effort"] in efforts
        ):
            raise _dependency_error()
        efforts.append(item["effort"])
    return tuple(efforts)


@dataclass(frozen=True, slots=True)
class _ResolvedProfileDependencies:
    """Digests of supplied transport/catalogue data, not verified provider truth."""

    provider_sha256: str
    provider_source_sha256: str
    catalogue_sha256: str | None
    selected_model_sha256: str | None


def _dependency_error(code: str = "model_profile_dependency_invalid") -> ContractError:
    return ContractError(code, "supply matching, bounded profile dependencies explicitly; no host discovery is used")


def _bounded(payload: object) -> bytes:
    if type(payload) is not bytes or not 0 < len(payload) <= 1_048_576:
        raise _dependency_error()
    return payload


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _dependency_error()
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    del value
    raise _dependency_error()


def _catalogue(payload: object, model: str) -> tuple[str, str]:
    blob = _bounded(payload)
    data = json.loads(blob.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_reject_constant)
    _json_values_are_bounded(data)
    if type(data) is not dict or set(data) != {"client_version", "models"}:
        raise _dependency_error()
    if type(data["client_version"]) is not str or not data["client_version"].strip():
        raise _dependency_error()
    models = data["models"]
    if type(models) is not list or not 1 <= len(models) <= 256:
        raise _dependency_error()
    slugs: set[str] = set()
    selected: dict[str, object] | None = None
    for entry in models:
        _validate_catalogue_entry(entry)
        slug = entry.get("slug")
        if type(slug) is not str or not slug.strip() or slug in slugs:
            raise _dependency_error()
        slugs.add(slug)
        if slug == model:
            selected = entry
    if selected is None:
        raise _dependency_error("model_profile_catalogue_mismatch")
    return hashlib.sha256(blob).hexdigest(), canonical_json_sha256(selected)


def _transport(profile: _ParsedCodexProfile, data: dict[str, object], payload: object) -> str:
    if profile.declares_provider:
        if payload is not None:
            raise _dependency_error("model_profile_dependency_ambiguous")
        providers = data["model_providers"]
    else:
        if payload is None:
            raise _dependency_error("model_profile_dependency_missing")
        root = tomllib.loads(_bounded(payload).decode("utf-8"))
        if set(root) != {"model_providers"}:
            raise _dependency_error()
        providers = root["model_providers"]
    if not _providers(providers, profile.provider):
        raise _dependency_error("model_profile_provider_mismatch")
    return canonical_json_sha256(providers[profile.provider])


def _resolve_profile_dependencies(
    profile: _ParsedCodexProfile, profile_bytes: bytes, provider_bytes: bytes | None, catalogue_bytes: bytes | None
) -> _ResolvedProfileDependencies:
    """Bind supplied dependencies; capture does not interpret catalogue semantics.

    The selected model entry is preserved by digest, including its instructions and
    defaults. A later execution adapter must prove its effective use; this reader
    does not validate arbitrary catalogue fields as executable Codex configuration.
    """
    try:
        if type(profile) is not _ParsedCodexProfile:
            raise _dependency_error("model_profile_input_changed")
        if _parse_codex_profile(profile_bytes, profile.lane) != profile:
            raise _dependency_error("model_profile_input_changed")
        data = tomllib.loads(profile_bytes.decode("utf-8"))
        transport = _transport(profile, data, provider_bytes)
        provider_source = profile_bytes if profile.declares_provider else _bounded(provider_bytes)
        provider_source_sha256 = hashlib.sha256(provider_source).hexdigest()
        if not profile.requires_catalogue:
            if catalogue_bytes is not None:
                raise _dependency_error("model_profile_dependency_ambiguous")
            return _ResolvedProfileDependencies(transport, provider_source_sha256, None, None)
        if catalogue_bytes is None:
            raise _dependency_error("model_profile_dependency_missing")
        catalogue, selected = _catalogue(catalogue_bytes, profile.model)
        return _ResolvedProfileDependencies(transport, provider_source_sha256, catalogue, selected)
    except ContractError:
        raise
    except (ValueError, TypeError, RecursionError, KeyError, OverflowError):
        raise _dependency_error() from None
