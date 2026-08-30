"""Draft 2020-12 projections for provider execution envelopes."""

from __future__ import annotations

from typing import Any

_PUBLIC_ID_PATTERN = (
    r"(^|[^A-Za-z0-9])(?:[aA][iI][zZ][aA]|[aA][kK][iI][aA]|[bB][eE][aA][rR][eE][rR]|"
    r"[gG][hH][pP]_|[gG][iI][tT][hH][uU][bB]_[pP][aA][tT]_|[hH][fF]_|[sS][kK]-|"
    r"[xX][oO][xX][bB]-|[xX][oO][xX][pP]-|(?:[aA][pP][iI][_-]?[kK][eE][yY]|"
    r"[cC][rR][eE][dD][eE][nN][tT][iI][aA][lL]|[pP][aA][sS][sS][wW][oO][rR][dD]|"
    r"""[sS][eE][cC][rR][eE][tT]|[tT][oO][kK][eE][nN])["']?\s*[:=])"""
)
_MACHINE_PATH_PATTERN = (
    r"(?:[fF][iI][lL][eE]:)?/+(?:[Uu][sS][eE][rR][sS]|[Hh][oO][mM][eE]|"
    r"[Pp][rR][iI][vV][aA][tT][eE]|[Tt][mM][pP]|[Ww][oO][rR][kK][sS][pP][aA][cC][eE]|"
    r"[Vv][aA][rR]/[Ff][oO][lL][dD][eE][rR][sS])/|"
    r"[A-Za-z]:[\\/]+(?:[Uu][sS][eE][rR][sS]|[Hh][oO][mM][eE])[\\/]|"
    r"(?:^|[\\/])(?:\$(?:\{)?(?:HOME|USER|USERPROFILE)(?:\})?|%(?:HOME|USER|USERPROFILE)%|"
    r"[Rr][Oo][Oo][Tt])(?:[\\/]|$)"
)
_RFC3339_PATTERN = r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"


def _reject_private_text_patterns(schema: dict[str, Any]) -> None:
    if schema.get("type") == "string":
        schema.setdefault("allOf", []).extend(
            ({"not": {"pattern": _PUBLIC_ID_PATTERN}}, {"not": {"pattern": _MACHINE_PATH_PATTERN}})
        )
    for branch in schema.get("anyOf", []):
        if isinstance(branch, dict):
            _reject_private_text_patterns(branch)


def _append_public_id_constraints(schema: dict[str, Any]) -> None:
    title = schema.get("title")
    properties = schema.get("properties", {})
    fields: tuple[str, ...] = ()
    if title == "ProviderExecutionRequest":
        fields = ("request_id", "scenario_set_id", "case_id", "package_safety_receipt_id")
    elif title == "ProviderExecutionResult":
        fields = ("result_id", "request_id", "scenario_set_id", "case_id", "replay_of_result_id")
    elif title == "PackageCandidateIdentity":
        fields = ("package_id",)
    for field in fields:
        _reject_private_text_patterns(properties[field])
    if title in {"ProviderExecutionBlocker", "ProviderExecutionError"}:
        _reject_private_text_patterns(properties["code"])
        _reject_private_text_patterns(properties["evidence_refs"]["items"])
    elif title in {"ProviderExecutionRequest", "ProviderExecutionResult"}:
        _reject_private_text_patterns(properties["evidence_refs"]["items"])
    for value in schema.values():
        if isinstance(value, dict):
            _append_public_id_constraints(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _append_public_id_constraints(item)


def append_provider_execution_constraints(schema: dict[str, Any], filename: str) -> None:
    """Project state-dependent provider execution invariants."""

    _append_public_id_constraints(schema)
    properties = schema["properties"]
    properties["evidence_refs"]["uniqueItems"] = True
    if filename == "provider-execution-request.v1.schema.json":
        properties["prepared_at"]["pattern"] = _RFC3339_PATTERN
        schema["$defs"]["ProviderExecutionBlocker"]["properties"]["evidence_refs"]["uniqueItems"] = True
        schema["allOf"] = [
            {
                "if": {"properties": {"status": {"const": "prepared"}}, "required": ["status"]},
                "then": {"properties": {"blocker": {"type": "null"}}},
            },
            {
                "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
                "then": {
                    "properties": {"blocker": {"$ref": "#/$defs/ProviderExecutionBlocker"}},
                    "required": ["blocker"],
                },
            },
        ]
    else:
        properties["started_at"]["pattern"] = _RFC3339_PATTERN
        properties["finished_at"]["pattern"] = _RFC3339_PATTERN
        schema["$defs"]["ProviderExecutionBlocker"]["properties"]["evidence_refs"]["uniqueItems"] = True
        schema["$defs"]["ProviderExecutionError"]["properties"]["evidence_refs"]["uniqueItems"] = True
        schema["allOf"] = [
            {
                "if": {
                    "properties": {"replay_of_result_id": {"type": "string"}},
                    "required": ["replay_of_result_id"],
                },
                "then": {
                    "properties": {"replay_of_result_sha256": {"type": "string"}},
                    "required": ["replay_of_result_sha256"],
                },
            },
            {
                "if": {
                    "properties": {"replay_of_result_sha256": {"type": "string"}},
                    "required": ["replay_of_result_sha256"],
                },
                "then": {
                    "properties": {"replay_of_result_id": {"type": "string"}},
                    "required": ["replay_of_result_id"],
                },
            },
            {
                "if": {"properties": {"status": {"const": "completed"}}, "required": ["status"]},
                "then": {
                    "properties": {
                        "output_sha256": {"type": "string"},
                        "evidence_refs": {"minItems": 1},
                        "blocker": {"type": "null"},
                        "error": {"type": "null"},
                    },
                    "required": ["output_sha256", "evidence_refs"],
                },
            },
            {
                "if": {"properties": {"status": {"const": "failed"}}, "required": ["status"]},
                "then": {
                    "properties": {
                        "output_sha256": {"type": "null"},
                        "blocker": {"type": "null"},
                        "error": {"$ref": "#/$defs/ProviderExecutionError"},
                    },
                    "required": ["error"],
                },
            },
            {
                "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
                "then": {
                    "properties": {
                        "output_sha256": {"type": "null"},
                        "usage": {"type": "null"},
                        "error": {"type": "null"},
                        "blocker": {"$ref": "#/$defs/ProviderExecutionBlocker"},
                    },
                    "required": ["blocker"],
                },
            },
            {
                "if": {"properties": {"status": {"const": "indeterminate"}}, "required": ["status"]},
                "then": {
                    "properties": {
                        "output_sha256": {"type": "null"},
                        "usage": {"type": "null"},
                        "blocker": {"type": "null"},
                        "error": {"$ref": "#/$defs/ProviderExecutionError"},
                    },
                    "required": ["error"],
                },
            },
        ]
    required_for = (
        ["request status and blocker must agree"]
        if filename == "provider-execution-request.v1.schema.json"
        else [
            "timestamps must be ordered",
            "usage totals must match their components",
            "a replay result cannot reference itself",
        ]
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": required_for,
        "external_inputs_required_for": (
            ["safety receipt identity, canonical digest, and candidate must match the supplied receipt"]
            if filename == "provider-execution-request.v1.schema.json"
            else [
                "request canonical digest and duplicated candidate, scenario, provider, and idempotency bindings must "
                "match the supplied request",
                "replay identity and canonical digest must match the supplied prior result",
            ]
        ),
    }


__all__ = ["append_provider_execution_constraints"]
