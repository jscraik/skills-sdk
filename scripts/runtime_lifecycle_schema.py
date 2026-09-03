"""JSON Schema projections for portable runtime-lock planning contracts."""

from __future__ import annotations

from typing import Any

from package_safety_schema import MACHINE_PATH_SCHEMA_PATTERN, PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN


def _safe_text_constraints() -> tuple[dict[str, Any], ...]:
    return (
        {"not": {"pattern": PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN}},
        {"not": {"pattern": MACHINE_PATH_SCHEMA_PATTERN}},
    )


def _extend_text_constraints(property_schema: dict[str, Any]) -> None:
    for branch in property_schema.get("anyOf", []):
        if branch.get("type") == "string":
            branch.setdefault("allOf", []).extend(_safe_text_constraints())
            return
    property_schema.setdefault("allOf", []).extend(_safe_text_constraints())


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
            if "evidence" in properties:
                properties["evidence"]["items"].setdefault("allOf", []).extend(_safe_text_constraints())
            for field in ("package_name", "version"):
                if field in properties:
                    properties[field].setdefault("allOf", []).extend(_safe_text_constraints())
            for field in (
                "package_receipt_id",
                "registry_preparation_receipt_id",
                "registry_input_receipt_id",
            ):
                if field in properties:
                    properties[field].setdefault("allOf", []).extend(_safe_text_constraints())
        elif title == "RuntimeAdapterIdentity":
            for field in ("adapter_id", "adapter_version"):
                properties[field].setdefault("allOf", []).extend(_safe_text_constraints())
        elif title == "RuntimeEvidenceBlocker":
            for field in ("code", "message"):
                properties[field].setdefault("allOf", []).extend(_safe_text_constraints())
            properties["evidence_refs"]["items"].setdefault("allOf", []).extend(_safe_text_constraints())
        elif title == "MutationRaceEvidence":
            properties["evidence_refs"]["items"].setdefault("allOf", []).extend(_safe_text_constraints())
        elif title == "RollbackJournalEntry":
            properties["path"].setdefault("allOf", []).extend(_safe_text_constraints())
            properties["evidence_refs"]["items"].setdefault("allOf", []).extend(_safe_text_constraints())
        elif title in {
            "InstallationResult",
            "RollbackJournal",
            "RollbackOutcome",
            "DiscoveryObservation",
            "ActivationObservation",
            "RuntimeOutcomeReceipt",
        }:
            for field in ("package_name", "version", "plan_id"):
                if field in properties:
                    properties[field].setdefault("allOf", []).extend(_safe_text_constraints())
            if "evidence" in properties:
                properties["evidence"]["items"].setdefault("allOf", []).extend(_safe_text_constraints())
            for field in (
                "receipt_id",
                "journal_id",
                "installation_result_id",
                "method_id",
                "discovery_receipt_id",
                "mechanism_id",
                "deactivation_id",
                "activation_receipt_id",
                "invocation_id",
                "provider_result_id",
                "evaluation_receipt_id",
            ):
                if field in properties:
                    _extend_text_constraints(properties[field])
        for value in schema.values():
            _append_public_text_constraints(value)
    elif isinstance(schema, list):
        for value in schema:
            _append_public_text_constraints(value)


def _append_runtime_evidence_constraints(schema: dict[str, Any], filename: str) -> None:
    properties = schema["properties"]
    properties["evidence"]["uniqueItems"] = True
    for definition in schema.get("$defs", {}).values():
        if not isinstance(definition, dict):
            continue
        definition_properties = definition.get("properties", {})
        for field in ("evidence", "evidence_refs"):
            if field in definition_properties:
                definition_properties[field]["uniqueItems"] = True
    state_rules: dict[str, list[dict[str, Any]]] = {
        "installation-result.v1.schema.json": [
            {
                "if": {"properties": {"operation": {"const": "no_change"}}, "required": ["operation"]},
                "then": {"properties": {"mutation_performed": {"const": False}}},
                "else": {
                    "if": {"properties": {"status": {"const": "completed"}}, "required": ["status"]},
                    "then": {"properties": {"mutation_performed": {"const": True}}},
                },
            },
            {
                "if": {"properties": {"status": {"const": "completed"}}, "required": ["status"]},
                "then": {
                    "required": ["resulting_lock_sha256"],
                    "properties": {
                        "blocker": {"type": "null"},
                        "race": {"type": "null"},
                        "resulting_lock_sha256": {"type": "string"},
                    },
                },
            },
            {
                "if": {"properties": {"status": {"enum": ["failed", "indeterminate"]}}, "required": ["status"]},
                "then": {
                    "required": ["blocker"],
                    "properties": {"blocker": {"$ref": "#/$defs/RuntimeEvidenceBlocker"}},
                },
            },
            {
                "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
                "then": {
                    "required": ["blocker"],
                    "properties": {
                        "blocker": {"$ref": "#/$defs/RuntimeEvidenceBlocker"},
                        "mutation_performed": {"const": False},
                        "resulting_lock_sha256": {"type": "null"},
                    },
                },
            },
        ],
        "rollback-outcome.v1.schema.json": [
            {
                "if": {"properties": {"status": {"const": "rolled_back"}}, "required": ["status"]},
                "then": {
                    "required": ["resulting_lock_sha256"],
                    "properties": {
                        "blocker": {"type": "null"},
                        "mutation_performed": {"const": True},
                        "race": {"type": "null"},
                        "resulting_lock_sha256": {"type": "string"},
                    },
                },
            },
            {
                "if": {
                    "properties": {"status": {"enum": ["rollback_failed", "indeterminate"]}},
                    "required": ["status"],
                },
                "then": {
                    "required": ["blocker"],
                    "properties": {"blocker": {"$ref": "#/$defs/RuntimeEvidenceBlocker"}},
                },
            },
            {
                "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
                "then": {
                    "required": ["blocker"],
                    "properties": {
                        "blocker": {"$ref": "#/$defs/RuntimeEvidenceBlocker"},
                        "mutation_performed": {"const": False},
                        "resulting_lock_sha256": {"type": "null"},
                    },
                },
            },
        ],
        "discovery-observation.v1.schema.json": [
            {
                "if": {"properties": {"status": {"const": "discovered"}}, "required": ["status"]},
                "then": {"properties": {"blocker": {"type": "null"}}},
            },
            {
                "if": {
                    "properties": {"status": {"enum": ["not_discovered", "blocked", "indeterminate"]}},
                    "required": ["status"],
                },
                "then": {
                    "required": ["blocker"],
                    "properties": {"blocker": {"$ref": "#/$defs/RuntimeEvidenceBlocker"}},
                },
            },
        ],
        "activation-observation.v1.schema.json": [
            {
                "if": {"properties": {"status": {"const": "active"}}, "required": ["status"]},
                "then": {"properties": {"blocker": {"type": "null"}}},
            },
            {
                "if": {
                    "properties": {"status": {"enum": ["inactive", "blocked", "indeterminate"]}},
                    "required": ["status"],
                },
                "then": {
                    "required": ["blocker"],
                    "properties": {"blocker": {"$ref": "#/$defs/RuntimeEvidenceBlocker"}},
                },
            },
            {
                "if": {"properties": {"mutation_performed": {"const": True}}, "required": ["mutation_performed"]},
                "then": {"required": ["deactivation_id"], "properties": {"deactivation_id": {"type": "string"}}},
            },
        ],
        "runtime-outcome.v1.schema.json": [
            {
                "if": {"properties": {"status": {"const": "completed"}}, "required": ["status"]},
                "then": {
                    "required": ["output_sha256"],
                    "properties": {"blocker": {"type": "null"}, "output_sha256": {"type": "string"}},
                },
            },
            {
                "if": {
                    "properties": {"status": {"enum": ["failed", "blocked", "indeterminate"]}},
                    "required": ["status"],
                },
                "then": {
                    "required": ["blocker"],
                    "properties": {"blocker": {"$ref": "#/$defs/RuntimeEvidenceBlocker"}},
                },
            },
        ],
    }
    if filename == "rollback-journal.v1.schema.json":
        properties["entries"]["uniqueItems"] = True
    if filename == "runtime-outcome.v1.schema.json":
        schema["dependentRequired"] = {
            "provider_result_id": ["provider_result_sha256"],
            "provider_result_sha256": ["provider_result_id"],
            "evaluation_receipt_id": ["evaluation_receipt_sha256"],
            "evaluation_receipt_sha256": ["evaluation_receipt_id"],
        }
    rules = [*schema.get("allOf", []), *state_rules.get(filename, [])]
    if rules:
        schema["allOf"] = rules
    schema["$comment"] = (
        "Validate cross-object candidate, plan, journal, discovery, activation, and outcome bindings with "
        "the explicit model validation methods; standard JSON Schema validates one payload structurally."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": [
            "candidate and package identity must match",
            "status fields must match blocker, mutation, and digest evidence",
            "installation operation must match lock transition digest equality",
            "rolled-back outcome requires every bound rollback journal entry to be applied",
            "evidence paths must be portable and unique",
            "upstream receipt equality requires the explicit validate_against method",
        ],
    }


def append_runtime_lifecycle_constraints(schema: dict[str, Any], filename: str) -> None:
    """Apply Draft-expressible state rules and document semantic checks."""

    _append_public_text_constraints(schema)
    runtime_lock_entry = schema.get("$defs", {}).get("RuntimeLockEntry")
    if runtime_lock_entry is not None:
        runtime_lock_entry["properties"]["files"]["uniqueItems"] = True
    if filename == "runtime-lock.v1.schema.json":
        schema["properties"]["entries"]["uniqueItems"] = True
        required_for = [
            "package name must match candidate package_id",
            "candidate content digest must match the runtime file inventory",
            "runtime entries must be unique by logical target and package",
            "runtime file paths must be unique within an entry",
        ]
    elif filename == "install-plan.v1.schema.json":
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
            "candidate content digest must match the proposed runtime file inventory",
            "runtime file paths must be unique within the proposed entry",
        ]
    else:
        _append_runtime_evidence_constraints(schema, filename)
        return
    schema["$comment"] = (
        "Validate cross-field lifecycle invariants with skills_sdk.core.schema_registry.SchemaRegistry.validate."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": required_for,
    }


__all__ = ["append_runtime_lifecycle_constraints"]
