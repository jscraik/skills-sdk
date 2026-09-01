"""JSON Schema projections for portable runtime-lock planning contracts."""

from __future__ import annotations

from typing import Any

from package_safety_schema import MACHINE_PATH_SCHEMA_PATTERN, PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN


def _safe_text_constraints() -> tuple[dict[str, Any], ...]:
    return (
        {"not": {"pattern": PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN}},
        {"not": {"pattern": MACHINE_PATH_SCHEMA_PATTERN}},
    )


def _append_public_text_constraints(schema: Any) -> None:
    if isinstance(schema, dict):
        title = schema.get("title")
        properties = schema.get("properties", {})
        if title == "RuntimeFile":
            properties["path"].setdefault("allOf", []).extend(_safe_text_constraints())
        elif title == "RuntimeTarget":
            properties["target_id"].setdefault("allOf", []).extend(_safe_text_constraints())
        elif title == "RuntimeLockEntry":
            for field in ("package_name", "version"):
                properties[field].setdefault("allOf", []).extend(_safe_text_constraints())
            for field in ("package_receipt_id", "registry_preparation_receipt_id"):
                properties[field].setdefault("allOf", []).extend(_safe_text_constraints())
        elif title == "RegistryPreparationBlocker":
            properties["code"].setdefault("allOf", []).extend(_safe_text_constraints())
            properties["message"].setdefault("allOf", []).extend(_safe_text_constraints())
            properties["evidence_refs"]["items"].setdefault("allOf", []).extend(_safe_text_constraints())
        elif title == "InstallPlan":
            properties["evidence"]["items"].setdefault("allOf", []).extend(_safe_text_constraints())
            for field in ("package_name", "version"):
                properties[field].setdefault("allOf", []).extend(_safe_text_constraints())
            for field in (
                "package_receipt_id",
                "registry_preparation_receipt_id",
                "registry_input_receipt_id",
            ):
                properties[field].setdefault("allOf", []).extend(_safe_text_constraints())
        for value in schema.values():
            _append_public_text_constraints(value)
    elif isinstance(schema, list):
        for value in schema:
            _append_public_text_constraints(value)


def append_runtime_lifecycle_constraints(schema: dict[str, Any], filename: str) -> None:
    """Apply Draft-expressible state rules and document semantic checks."""

    _append_public_text_constraints(schema)
    schema["$defs"]["RuntimeLockEntry"]["properties"]["files"]["uniqueItems"] = True
    if filename == "runtime-lock.v1.schema.json":
        schema["properties"]["entries"]["uniqueItems"] = True
        required_for = [
            "package name must match candidate package_id",
            "runtime entries must be unique by logical target and package",
            "runtime file paths must be unique within an entry",
        ]
    else:
        properties = schema["properties"]
        properties["evidence"]["uniqueItems"] = True
        schema["allOf"] = [
            {
                "if": {"properties": {"status": {"const": "planned"}}, "required": ["status"]},
                "then": {
                    "required": ["candidate", "package_digest", "operation", "proposed_lock_sha256", "proposed_entry"],
                    "properties": {
                        "candidate": {"$ref": "#/$defs/PackageCandidateIdentity"},
                        "package_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                        "operation": {"enum": ["install", "update", "no_change"]},
                        "proposed_lock_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                        "proposed_entry": {"$ref": "#/$defs/RuntimeLockEntry"},
                        "blocker": {"type": "null"},
                    },
                },
            },
            {
                "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
                "then": {
                    "required": ["blocker"],
                    "properties": {
                        "blocker": {"$ref": "#/$defs/RegistryPreparationBlocker"},
                        "operation": {"type": "null"},
                        "proposed_lock_sha256": {"type": "null"},
                        "proposed_entry": {"type": "null"},
                    },
                },
            },
        ]
        required_for = [
            "registry input receipt must match package receipt",
            "rollback digest must match current lock digest",
            "planned entry must bind candidate, digest, registry, and target",
            "plan and entry must bind the same package name and version",
            "plan and entry must bind the same package and registry preparation receipts",
            "plan id must bind the complete emitted plan identity",
            "no-change operations must preserve the current lock digest",
            "install and update operations must change the current lock digest",
            "runtime file paths must be unique within the proposed entry",
        ]
    schema["$comment"] = (
        "Validate cross-field lifecycle invariants with skills_sdk.core.schema_registry.SchemaRegistry.validate."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": required_for,
    }


__all__ = ["append_runtime_lifecycle_constraints"]
