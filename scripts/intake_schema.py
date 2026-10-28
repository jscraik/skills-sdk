"""Project expressible constraints for the additive intake receipt only."""

from typing import Any


def append_intake_family_constraints(schema: dict[str, Any], filename: str) -> None:
    """Project intake metadata without changing frozen or unrelated schemas."""
    if filename == "skill-package-intake.v1.schema.json":
        append_intake_constraints(schema)
    if filename in {
        "saved-release-snapshot.v1.schema.json",
        "saved-release-provenance.v1.schema.json",
        "saved-release-package-source.v1.schema.json",
        "normalized-package.v2.schema.json",
        "skill-package-intake-context.v2.schema.json",
        "skill-package-intake.v2.schema.json",
        "local-check-request.v3.schema.json",
        "local-check.v3.schema.json",
        "plugin-quality-request.v2.schema.json",
        "plugin-quality.v2.schema.json",
    }:
        schema["x-skills-sdk-semantic-validation"] = {
            "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
            "required_for": [
                "saved descriptor fingerprint, root, mode, revision and selected-child bindings",
                "ordered quality receipts and unchanged source captures",
                "admission decisions preserve supplied checks without authenticating provenance",
            ],
        }


def append_intake_constraints(schema: dict[str, Any]) -> None:
    """Keep legacy package schemas frozen while describing intake proof limits."""
    definitions = schema["$defs"]
    definitions["IntakeDecision"]["allOf"] = [
        {
            "if": {"properties": {"decision": {"const": "admit"}}, "required": ["decision"]},
            "then": {
                "properties": {
                    "checks": {
                        "properties": {
                            key: {"const": True} for key in ("identity", "provenance", "rights", "owner_unchanged")
                        }
                    },
                    "blocker_codes": {"maxItems": 0},
                }
            },
            "else": {"properties": {"blocker_codes": {"minItems": 1}}, "required": ["blocker_codes"]},
        }
    ]
    definitions["NormalizedPackage"]["allOf"] = [
        {
            "if": {"properties": {"package_type": {"const": package_type}}, "required": ["package_type"]},
            "then": {"properties": {"identity": {"properties": {"package_type": {"const": package_type}}}}},
        }
        for package_type in ("skill", "plugin")
    ]
    schema["x-skills-sdk-semantic-validation"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": [
            "candidate, source, context, decision and normalized package identities must agree",
            "candidate content digest must match the sorted validation files",
            "decision and blocker must match their persisted validation and admission evidence",
        ],
    }
