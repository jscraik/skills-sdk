"""Generated-schema constraints for scorer assessment receipts."""

from __future__ import annotations

from typing import Any


def append_scorer_receipt_constraints(schema: dict[str, Any], filename: str) -> None:
    """Project receipt state requirements into standalone portable schemas."""

    finding = schema["$defs"]["ScenarioQualityFinding"]["properties"]
    finding["message"]["pattern"] = r".*\S.*"
    finding["case_id"]["anyOf"][0]["pattern"] = r".*\S.*"
    quality = filename == "scorer-quality.v1.schema.json"
    pass_properties: dict[str, Any] = {
        "candidate": {"$ref": "#/$defs/PackageCandidateIdentity"},
        "findings": {"maxItems": 0},
        "scorer_id": {"minLength": 1, "pattern": r".*\S.*"},
        "scorer_version_or_digest": {"minLength": 1, "pattern": r".*\S.*"},
    }
    pass_required = ["candidate", "scorer_id", "scorer_version_or_digest"]
    if quality:
        pass_properties.update(
            calibration_probe_count={"minimum": 6},
            pass_threshold={"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        )
        pass_required.extend(("calibration_probe_count", "pass_threshold"))
    else:
        schema["$defs"]["ScorerJudgeParameters"]["properties"]["model"]["pattern"] = r".*\S.*"
        pass_properties.update(
            example_count={"minimum": 1},
            effective_policy={"$ref": "#/$defs/ScorerCalibrationAppliedPolicy"},
            parameters={"$ref": "#/$defs/ScorerJudgeParameters"},
            prompt_version={"minLength": 1, "pattern": r".*\S.*"},
        )
        pass_required.extend(("example_count", "effective_policy", "parameters", "prompt_version"))

    schema["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "pass"}}, "required": ["status"]},
            "then": {"required": pass_required, "properties": pass_properties},
        },
        {
            "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
            "then": {"required": ["findings"], "properties": {"findings": {"minItems": 1}}},
        },
    ]
    if not quality:
        schema["$comment"] = (
            "Validate confusion-matrix arithmetic, rates, and effective policy with "
            "skills_sdk.core.schema_registry.SchemaRegistry.validate."
        )
        schema["x-skills-sdk-semantic-validator"] = {
            "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
            "required_for": ["passing calibration metrics must match the confusion matrix and effective policy"],
        }


__all__ = ["append_scorer_receipt_constraints"]
