"""JSON-expressible constraints for the generated local-check envelope."""

from __future__ import annotations

from typing import Any

_STAGES = (
    ("intake", "SkillPackageIntakeReceipt"),
    ("validate", "SkillPackageValidation"),
    ("scenario-quality", "ScenarioQualityReceiptV2"),
    ("scorer-quality", "ScorerQualityReceipt"),
    ("scorer-calibration", "ScorerCalibrationReceipt"),
)


def _stage(name: str, receipt_type: str, *, status: str | None = None) -> dict[str, Any]:
    receipt: dict[str, Any] = {"$ref": f"#/$defs/{receipt_type}"}
    if status is not None:
        receipt = {"allOf": [receipt, {"properties": {"status": {"const": status}}, "required": ["status"]}]}
    return {
        "allOf": [
            {"$ref": "#/$defs/LocalCheckStage"},
            {"properties": {"name": {"const": name}, "receipt": receipt}, "required": ["name", "receipt"]},
        ]
    }


def append_local_check_constraints(schema: dict[str, Any]) -> None:
    """Enforce wire-visible shape and state; reserve comparisons for the model."""
    schema["required"] = [
        "schema_version",
        "workflow",
        "status",
        "candidate",
        "blocked_stage",
        "stages",
        "blocker",
        "promotion_authorized",
        "mutation_performed",
        "network_used",
        "execution_performed",
    ]
    schema["allOf"] = [
        {
            "properties": {
                "stages": {
                    "prefixItems": [_stage(name, receipt) for name, receipt in _STAGES],
                    "items": False,
                    "maxItems": len(_STAGES),
                }
            }
        },
        {
            "if": {"properties": {"status": {"const": "local_checks_passed"}}, "required": ["status"]},
            "then": {
                "properties": {
                    "candidate": {"$ref": "#/$defs/PackageCandidateIdentity"},
                    "blocked_stage": {"type": "null"},
                    "blocker": {"type": "null"},
                    "stages": {
                        "minItems": len(_STAGES),
                        "maxItems": len(_STAGES),
                        "prefixItems": [
                            _stage(name, receipt, status="normalized" if name == "intake" else "pass")
                            for name, receipt in _STAGES
                        ],
                    },
                }
            },
        },
        {
            "if": {"properties": {"blocked_stage": {"const": "context"}}, "required": ["blocked_stage"]},
            "then": {
                "properties": {
                    "status": {"const": "blocked"},
                    "candidate": {"type": "null"},
                    "stages": {"maxItems": 0},
                    "blocker": {
                        "allOf": [
                            {"$ref": "#/$defs/PackageReceiptBlocker"},
                            {"properties": {"code": {"const": "unsupported_context_read"}}},
                        ]
                    },
                }
            },
            "else": {"properties": {"stages": {"minItems": 1}, "blocker": {"type": "null"}}},
        },
        {
            "if": {"properties": {"blocked_stage": {"const": "candidate_changed"}}, "required": ["blocked_stage"]},
            "then": {"properties": {"status": {"const": "blocked"}, "stages": {"minItems": 2}}},
        },
    ]
    for index, (name, receipt_type) in enumerate(_STAGES, 1):
        schema["allOf"].append(
            {
                "if": {"properties": {"blocked_stage": {"const": name}}, "required": ["blocked_stage"]},
                "then": {
                    "properties": {
                        "status": {"const": "blocked"},
                        "stages": {
                            "minItems": index,
                            "maxItems": index,
                            "prefixItems": [
                                _stage(stage_name, stage_receipt, status="normalized" if offset == 0 else "pass")
                                for offset, (stage_name, stage_receipt) in enumerate(_STAGES[: index - 1])
                            ]
                            + [_stage(name, receipt_type, status="blocked" if index > 1 else None)],
                        },
                    }
                },
            }
        )
    schema["$comment"] = (
        "Use SchemaRegistry.validate for candidate equality, intake admission, first-blocker semantics, "
        "and nested receipt invariants; JSON Schema cannot compare arbitrary stage fields."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": [
            "stage candidates must match the intake candidate",
            "intake admission and first-blocker ordering must hold",
            "nested receipt models must satisfy their semantic invariants",
        ],
    }


__all__ = ["append_local_check_constraints"]
