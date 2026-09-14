"""Generated-schema constraints for scenario-quality receipts."""

from __future__ import annotations

from typing import Any


def append_scenario_quality_constraints(schema: dict[str, Any]) -> None:
    """Project scenario-quality receipt state and scope invariants."""

    schema["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "pass"}}, "required": ["status"]},
            "then": {
                "required": ["candidate", "scenario_count"],
                "properties": {
                    "candidate": {"$ref": "#/$defs/PackageCandidateIdentity"},
                    "scenario_count": {"minimum": 1},
                    "findings": {"maxItems": 0},
                },
            },
        },
        {
            "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
            "then": {
                "required": ["findings"],
                "properties": {"findings": {"minItems": 1}},
            },
        },
        {
            "if": {"properties": {"scope": {"const": "release"}}, "required": ["scope"]},
            "then": {
                "required": ["scenario_set_id"],
                "properties": {"scenario_set_id": {"type": "string", "minLength": 1}},
            },
            "else": {"properties": {"scenario_set_id": {"type": "null"}}},
        },
    ]


__all__ = ["append_scenario_quality_constraints"]
