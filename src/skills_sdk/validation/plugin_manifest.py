"""Parse captured Agent Plugins metadata without reading paths or executing it."""

from __future__ import annotations

import hashlib
import json
import math

from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI, PortablePluginManifest
from skills_sdk.models.validation import SkillPackageFinding, ValidationSeverity

_KNOWN = frozenset(
    {
        "$schema",
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "extensions",
    }
)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate plugin JSON member")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("plugin metadata requires standard JSON constants")


def _check_json_budget(value: object) -> None:
    stack, remaining = [(value, 0)], 65536
    while stack:
        item, depth = stack.pop()
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise ValueError("plugin metadata exceeds parsing budget")
        if isinstance(item, str):
            item.encode("utf-8")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("plugin metadata number exceeds finite range")
        elif isinstance(item, dict):
            stack.extend((member, depth + 1) for pair in item.items() for member in pair)
        elif isinstance(item, list):
            stack.extend((member, depth + 1) for member in item)


def _object(payload: bytes) -> dict[str, object]:
    if len(payload) > 1_048_576:
        raise ValueError("plugin metadata exceeds one MiB")
    parsed = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant)
    _check_json_budget(parsed)
    if not isinstance(parsed, dict):
        raise ValueError("plugin metadata must be an object")
    return parsed


def _known_fields(value: dict[str, object]) -> None:
    if value.get("$schema") != PLUGIN_SCHEMA_URI or type(value.get("name")) is not str:
        raise ValueError("plugin requires its supported schema and name")
    for key in ("version", "description", "homepage", "repository", "license"):
        if key in value and type(value[key]) is not str:
            raise ValueError("plugin metadata has a wrongly typed known field")
    if "author" in value:
        author = value["author"]
        if (
            type(author) is not dict
            or set(author) - {"name", "email", "url"}
            or any(type(item) is not str for item in author.values())
        ):
            raise ValueError("plugin author must be a closed object of strings")
    if "keywords" in value:
        keywords = value["keywords"]
        if type(keywords) is not list or any(type(item) is not str for item in keywords):
            raise ValueError("plugin keywords must be an array of strings")


def parse_plugin_manifest(payloads: dict[str, bytes]) -> tuple[PortablePluginManifest, tuple[SkillPackageFinding, ...]]:
    """Retain root identity and selected OpenAI settings, never merge overlays."""
    payload = payloads["plugin.json"]
    value = _object(payload)
    _known_fields(value)
    warnings: list[SkillPackageFinding] = []
    if set(value) - _KNOWN:
        warnings.append(
            SkillPackageFinding(
                code="plugin_unknown_fields_ignored",
                severity=ValidationSeverity.WARNING,
                message="unknown root manifest fields were ignored",
                evidence_refs=("plugin.json",),
            )
        )
    extensions = value.get("extensions", {})
    if type(extensions) is not dict:
        warnings.append(
            SkillPackageFinding(
                code="plugin_extensions_ignored",
                severity=ValidationSeverity.WARNING,
                message="non-object extensions were ignored",
                evidence_refs=("plugin.json",),
            )
        )
        extensions = {}
    inline = extensions.get("com.openai")
    selected, source = None, "none"
    if type(inline) is dict:
        selected, source = inline, "inline"
    elif ".codex-plugin/plugin.json" in payloads:
        selected, source = _object(payloads[".codex-plugin/plugin.json"]), "compatibility"
    return PortablePluginManifest.model_validate(
        {
            "name": value["name"],
            "version": value.get("version"),
            "description": value.get("description"),
            "source_sha256": hashlib.sha256(payload).hexdigest(),
            "openai_settings_source": source,
            "openai_settings": selected,
        }
    ), tuple(warnings)
