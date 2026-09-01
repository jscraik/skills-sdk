"""JSON Schema projections for package-safety-evidence/v1."""

from __future__ import annotations

from typing import Any, Final, Protocol


class SchemaModel(Protocol):
    """Minimal generated-schema model surface."""

    @classmethod
    def model_json_schema(cls) -> dict[str, Any]: ...


PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN = (
    r"(^|[^A-Za-z0-9])(?:[aA][iI][zZ][aA]|[aA][kK][iI][aA]|[bB][eE][aA][rR][eE][rR]|"
    r"[gG][hH][pP]_|[gG][iI][tT][hH][uU][bB]_[pP][aA][tT]_|[hH][fF]_|[sS][kK]-|"
    r"[xX][oO][xX][bB]-|[xX][oO][xX][pP]-|"
    r"-----[Bb][Ee][Gg][Ii][Nn](?: [A-Za-z0-9]+)? [Pp][Rr][Ii][Vv][Aa][Tt][Ee] [Kk][Ee][Yy]-----|"
    r"[eE][yY][jJ][A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"(?:[cC][lL][iI][eE][nN][tT]|[aA][cC][cC][eE][sS][sS])[_-]?(?:[sS][eE][cC][rR][eE][tT]|"
    r"[tT][oO][kK][eE][nN]|[kK][eE][yY](?:[_-]?[iI][dD])?)|"
    r"(?:(?:[sS][sS][hH]_)?[pP][rR][iI][vV][aA][tT][eE][_-]?[kK][eE][yY]|"
    r"[aA][pP][iI][_-]?[kK][eE][yY]|[cC][rR][eE][dD][eE][nN][tT][iI][aA][lL]|"
    r"[pP][aA][sS][sS][wW][oO][rR][dD]|[sS][eE][cC][rR][eE][tT]|[tT][oO][kK][eE][nN])"
    r"(?:[_-][A-Za-z0-9]+)*"
    r"[\"']?[\s\u001c-\u001f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*[:=])"
)
MACHINE_PATH_SCHEMA_PATTERN = (
    r"(?:[fF][iI][lL][eE]:)/+|(?:^|[^A-Za-z0-9])\$[A-Za-z_][A-Za-z0-9_]*/|"
    r"(?:[A-Za-z0-9._-]+\\)+[A-Za-z0-9._-]+|(?:^|[^A-Za-z0-9])\\|(?:^|[^A-Za-z0-9/])/(?!/)|"
    r"(?:^|[^A-Za-z0-9/])/(?:[Uu][sS][eE][rR][sS]|[Hh][oO][mM][eE]|[Pp][rR][iI][vV][aA][tT][eE]|"
    r"[Tt][mM][pP]|[Ww][oO][rR][kK][sS][pP][aA][cC][eE]|[Vv][aA][rR]/[Ff][oO][lL][dD][eE][rR][sS]|"
    r"[Rr][Oo][Oo][Tt])/|"
    r"(?:^|[^A-Za-z0-9.:/])(?:[A-Za-z0-9._-]+/)+(?:[Uu][sS][eE][rR][sS]|[Hh][oO][mM][eE]|"
    r"[Pp][rR][iI][vV][aA][tT][eE]|[Tt][mM][pP]|[Ww][oO][rR][kK][sS][pP][aA][cC][eE]|"
    r"[Vv][aA][rR]/[Ff][oO][lL][dD][eE][rR][sS]|[Rr][Oo][Oo][Tt])/|"
    r"(?:^|[^A-Za-z0-9])[A-Za-z]:"
)
RFC3339_DATETIME_SCHEMA_PATTERN: Final[str] = (
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])[Tt]"
    r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?"
    r"(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)


def append_package_safety_identity_constraints(
    schema: Any,
    credential_pattern: str,
    machine_path_pattern: str,
) -> None:
    """Project secret-free public fields into package safety schemas."""

    if isinstance(schema, dict):
        title = schema.get("title")
        properties = schema.get("properties", {})
        if title == "PackageSafetyReviewer":
            for field in ("adapter_id", "adapter_version_or_digest"):
                properties[field].setdefault("allOf", []).extend(
                    ({"not": {"pattern": credential_pattern}}, {"not": {"pattern": machine_path_pattern}})
                )
        elif title == "PackageSafetyEvidenceReference":
            properties["evidence_id"]["not"] = {"pattern": credential_pattern}
            properties["ref"].setdefault("allOf", []).extend(
                ({"not": {"pattern": credential_pattern}}, {"not": {"pattern": machine_path_pattern}})
            )
        elif title == "PackageSafetyFinding":
            for field in ("code", "message"):
                properties[field].setdefault("allOf", []).extend(
                    ({"not": {"pattern": credential_pattern}}, {"not": {"pattern": machine_path_pattern}})
                )
            properties["evidence_ids"]["items"].setdefault("allOf", []).extend(
                ({"not": {"pattern": credential_pattern}}, {"not": {"pattern": machine_path_pattern}})
            )
            properties["message"].setdefault("allOf", []).append({"pattern": r"\S"})
        elif title == "PackageSafetyBlocker":
            for field in ("code", "message"):
                properties[field].setdefault("allOf", []).extend(
                    ({"not": {"pattern": credential_pattern}}, {"not": {"pattern": machine_path_pattern}})
                )
            properties["evidence_refs"]["items"].setdefault("allOf", []).extend(
                ({"not": {"pattern": credential_pattern}}, {"not": {"pattern": machine_path_pattern}})
            )
            properties["message"].setdefault("allOf", []).append({"pattern": r"\S"})
        elif title == "PackageSafetyEvidenceReceipt":
            for field in ("receipt_id", "input_receipt_id"):
                properties[field]["not"] = {"pattern": credential_pattern}
        for value in schema.values():
            append_package_safety_identity_constraints(value, credential_pattern, machine_path_pattern)
    elif isinstance(schema, list):
        for value in schema:
            append_package_safety_identity_constraints(value, credential_pattern, machine_path_pattern)


def append_package_safety_constraints(schema: dict[str, Any]) -> None:
    """Project JSON-Schema-expressible package safety state invariants."""

    properties = schema["properties"]
    properties["observed_at"]["pattern"] = RFC3339_DATETIME_SCHEMA_PATTERN
    for field in ("evidence", "findings", "blockers"):
        properties[field]["uniqueItems"] = True
    schema["$defs"]["PackageSafetyFinding"]["properties"]["evidence_ids"]["uniqueItems"] = True
    schema["$defs"]["PackageSafetyBlocker"]["properties"]["evidence_refs"]["uniqueItems"] = True
    schema["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "not_reviewed"}}, "required": ["status"]},
            "then": {
                "properties": {
                    "evidence": {"maxItems": 0},
                    "findings": {"maxItems": 0},
                    "blocker": {"type": "null"},
                    "blockers": {"maxItems": 0},
                }
            },
        },
        {
            "if": {"properties": {"status": {"const": "reviewed_no_issue"}}, "required": ["status"]},
            "then": {
                "properties": {
                    "evidence": {"minItems": 1},
                    "findings": {"maxItems": 0},
                    "blocker": {"type": "null"},
                    "blockers": {"maxItems": 0},
                },
                "required": ["evidence"],
            },
        },
        {
            "if": {"properties": {"status": {"const": "issue_found"}}, "required": ["status"]},
            "then": {
                "properties": {
                    "evidence": {"minItems": 1},
                    "findings": {
                        "minItems": 1,
                        "contains": {
                            "properties": {"severity": {"enum": ["warning", "blocker"]}},
                            "required": ["severity"],
                        },
                    },
                    "blocker": {"$ref": "#/$defs/PackageSafetyBlocker"},
                    "blockers": {"minItems": 1},
                },
                "required": ["evidence", "findings", "blocker", "blockers"],
            },
        },
        {
            "if": {"properties": {"status": {"const": "metadata_insufficient"}}, "required": ["status"]},
            "then": {
                "properties": {
                    "findings": {"maxItems": 0},
                    "blocker": {"$ref": "#/$defs/PackageSafetyBlocker"},
                    "blockers": {"minItems": 1},
                },
                "required": ["blocker", "blockers"],
            },
        },
    ]
    schema["$comment"] = (
        "Validate evidence-id references, unique finding codes, and primary blocker ordering with "
        "skills_sdk.core.schema_registry.SchemaRegistry.validate."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": [
            "findings must reference supplied evidence ids",
            "finding codes, evidence ids, and evidence refs must be unique",
            "issue and insufficient states must retain the primary blocker first",
            "blocker evidence refs must resolve to supplied digest-bound evidence",
        ],
        "external_entrypoint": (
            "skills_sdk.core.schema_registry.SchemaRegistry.validate_package_safety_evidence_against_package_receipt"
        ),
        "external_inputs_required_for": [
            "input receipt id, candidate, and package digest must match a supplied package-receipt/v2",
        ],
    }


def append_package_safety_schema_constraints(schema: dict[str, Any], filename: str) -> None:
    """Project package-safety constraints into generated schemas."""

    append_package_safety_identity_constraints(
        schema,
        PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN,
        MACHINE_PATH_SCHEMA_PATTERN,
    )
    if filename == "package-safety-evidence.v1.schema.json":
        append_package_safety_constraints(schema)


__all__ = [
    "MACHINE_PATH_SCHEMA_PATTERN",
    "PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN",
    "RFC3339_DATETIME_SCHEMA_PATTERN",
    "SchemaModel",
    "append_package_safety_constraints",
    "append_package_safety_identity_constraints",
    "append_package_safety_schema_constraints",
]
