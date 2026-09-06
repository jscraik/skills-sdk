"""Project expressible constraints for the additive intake receipt only."""

from typing import Any


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
