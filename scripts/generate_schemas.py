#!/usr/bin/env python3
"""Generate committed JSON Schemas from the public Pydantic contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from skills_sdk.models.evaluation import ScenarioSet, ScorerProfile
from skills_sdk.models.inventory import (
    PackageInventory,
    PackageInventoryRecord,
    PackageInventoryRecordV2,
    PackageInventoryV2,
)
from skills_sdk.models.package import (
    IntakeDecision,
    NormalizedPackage,
    PackageCandidateIdentity,
    PackageOwner,
    PackageSource,
    PluginIdentity,
    SkillIdentity,
)
from skills_sdk.models.packaging import PackageHardeningReceipt, PackageManifest, PackageReceipt
from skills_sdk.models.risk import RiskClassification, SecurityScreeningResult
from skills_sdk.models.validation import SkillPackageValidation

_PORTABLE_PATH_PATTERN = (
    r"^(?=.*\S)(?!.*[\r\n])(?!/)(?!.*\\)(?!.*(?:^|/)\.\.?(?:/|$))(?![^/]*:)"
    r"(?!.*//)(?!.*(?:^|/)\./)(?!.*\/$)[\s\S]+$"
)
_NON_WHITESPACE_TEXT_PATTERN = r"^[\s\S]*\S[\s\S]*$"
_NORMALIZED_TEXT_PATTERN = r"^\S(?:[\s\S]*\S)?$"


def _append_portable_path_constraints(schema: Any) -> None:
    """Project the shared PortablePath contract into every generated schema node."""

    if isinstance(schema, dict):
        if schema.pop("x-skills-sdk-portable-path", False):
            schema["pattern"] = _PORTABLE_PATH_PATTERN
        for value in schema.values():
            _append_portable_path_constraints(value)
    elif isinstance(schema, list):
        for value in schema:
            _append_portable_path_constraints(value)


def _append_risk_constraints(schema: dict[str, Any]) -> None:
    """Add JSON-Schema-expressible risk invariants to the generated contract."""

    schema["properties"]["sensor_ids"]["uniqueItems"] = True
    schema["properties"]["sensors"]["uniqueItems"] = True
    schema["properties"]["sensor_ids"]["items"]["pattern"] = _NORMALIZED_TEXT_PATTERN
    schema["$defs"]["RiskSensor"]["properties"]["id"]["pattern"] = _NORMALIZED_TEXT_PATTERN
    schema["properties"]["acceptance_trace"]["items"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
    schema["allOf"] = [
        *schema.get("allOf", []),
        {
            "if": {
                "properties": {"risk_tier": {"enum": ["high", "privileged", "published"]}},
                "required": ["risk_tier"],
            },
            "then": {
                "properties": {"receipt_required": {"const": True}},
                "required": ["receipt_required"],
            },
        },
        {
            "if": {"required": ["sensors"]},
            "then": {
                "not": {
                    "properties": {
                        "sensors": {
                            "contains": {
                                "allOf": [
                                    {"properties": {"required": {"const": True}}, "required": ["required"]},
                                    {
                                        "anyOf": [
                                            {
                                                "properties": {
                                                    "status": {"enum": ["available_not_run", "skipped_optional"]}
                                                },
                                                "required": ["status"],
                                            },
                                            {
                                                "properties": {"blocking_behavior": {"const": "skip_optional"}},
                                                "required": ["blocking_behavior"],
                                            },
                                        ]
                                    },
                                ]
                            }
                        }
                    }
                }
            }
        },
        {
            "not": {
                "properties": {
                    "receipt_required": {"const": False},
                    "sensors": {
                        "contains": {
                            "allOf": [
                                {"properties": {"status": {"const": "selected"}}, "required": ["status"]},
                                {"properties": {"receipt_required": {"const": True}}, "required": ["receipt_required"]},
                            ]
                        }
                    },
                },
                "required": ["receipt_required", "sensors"],
            }
        },
    ]
    schema["$comment"] = (
        "Validate risk sensor-id coverage with "
        "skills_sdk.core.schema_registry.SchemaRegistry.validate; standard JSON Schema "
        "cannot compare the two arbitrary identifier arrays."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": ["sensor_ids must match declared sensor ids", "risk sensor ids must be unique"],
    }


def _append_security_constraints(schema: dict[str, Any]) -> None:
    """Add JSON-Schema-expressible security invariants to the generated contract."""

    schema["properties"]["scanned_paths"]["items"]["pattern"] = _PORTABLE_PATH_PATTERN
    schema["properties"]["sensor_ids"]["items"]["pattern"] = _NORMALIZED_TEXT_PATTERN
    schema["properties"]["sensor_ids"]["uniqueItems"] = True
    schema["$defs"]["SecurityFinding"]["properties"]["evidence_refs"]["items"]["pattern"] = _PORTABLE_PATH_PATTERN
    schema["$defs"]["SecurityFinding"]["properties"]["code"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
    schema["$defs"]["SecurityFinding"]["properties"]["message"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
    schema["allOf"] = [
        *schema.get("allOf", []),
        {
            "if": {"properties": {"status": {"const": "pass"}}, "required": ["status"]},
            "then": {
                "not": {
                    "required": ["findings"],
                    "properties": {
                        "findings": {
                            "contains": {
                                "properties": {"severity": {"enum": ["warning", "blocker"]}},
                                "required": ["severity"],
                            }
                        }
                    }
                }
            },
        },
        {
            "if": {"properties": {"status": {"const": "needs_review"}}, "required": ["status"]},
            "then": {
                "allOf": [
                    {
                        "required": ["findings"],
                        "properties": {
                            "findings": {
                                "contains": {
                                    "properties": {"severity": {"const": "warning"}},
                                    "required": ["severity"],
                                }
                            }
                        },
                    },
                    {
                        "not": {
                            "properties": {
                                "findings": {
                                    "contains": {
                                        "properties": {"severity": {"const": "blocker"}},
                                        "required": ["severity"],
                                    }
                                }
                            }
                        }
                    },
                ]
            },
        },
        {
            "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
            "then": {
                "required": ["findings"],
                "properties": {
                    "findings": {
                        "contains": {
                            "properties": {"severity": {"const": "blocker"}},
                            "required": ["severity"],
                        }
                    }
                },
            },
        },
    ]
    schema["$comment"] = (
        "Validate finding-code uniqueness with "
        "skills_sdk.core.schema_registry.SchemaRegistry.validate; standard JSON Schema "
        "cannot compare arbitrary object fields."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": ["security finding codes must be unique"],
    }


def _append_evaluation_constraints(schema: dict[str, Any], filename: str) -> None:
    """Project evaluation policy invariants into the committed schemas."""

    if filename == "scenario-set.v1.schema.json":
        scenario_case_properties = schema["$defs"]["ScenarioCase"]["properties"]
        scenario_case_properties["case_id"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        scenario_case_properties["prompt"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        scenario_case_properties["expected_signals"]["items"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        scenario_case_properties["forbidden_commands"]["items"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        schema["properties"]["scenario_set_id"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        schema["properties"]["cases"]["items"]["$ref"] = "#/$defs/ScenarioCase"
        schema["allOf"] = [
            *schema.get("allOf", []),
            {
                "if": {"properties": {"release": {"const": True}}, "required": ["release"]},
                "then": {
                    "required": ["cases"],
                    "properties": {
                        "cases": {
                            "contains": {
                                "properties": {"category": {"const": "regression"}},
                                "required": ["category"],
                            }
                        }
                    },
                },
            },
        ]
        schema["$comment"] = (
            "Validate scenario-case identifier uniqueness and release regression coverage with "
            "skills_sdk.core.schema_registry.SchemaRegistry.validate."
        )
        schema["x-skills-sdk-semantic-validator"] = {
            "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
            "required_for": ["scenario case ids must be unique"],
        }
    elif filename == "scorer-profile.v1.schema.json":
        properties = schema["properties"]
        properties["scorer_id"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        properties["version_or_digest"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        properties["calibration_probe_ids"]["items"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        properties["calibration_probe_ids"]["uniqueItems"] = True
        schema["allOf"] = [
            *schema.get("allOf", []),
            {
                "if": {
                    "properties": {"calibration_required": {"const": True}},
                    "required": ["calibration_required"],
                },
                "then": {
                    "required": ["calibration_probe_ids"],
                    "properties": {"calibration_probe_ids": {"minItems": 1}},
                },
            },
            {
                "if": {
                    "properties": {"scorer_type": {"enum": ["llm_judge", "external"]}},
                    "required": ["scorer_type"],
                },
                "then": {
                    "required": ["calibration_required", "calibration_probe_ids", "deterministic_checks_first"],
                    "properties": {
                        "calibration_required": {"const": True},
                        "calibration_probe_ids": {"minItems": 1},
                        "deterministic_checks_first": {"const": True},
                    },
                },
            },
        ]
        schema["$comment"] = (
            "Validate calibration and deterministic-first policy with "
            "skills_sdk.core.schema_registry.SchemaRegistry.validate."
        )
        schema["x-skills-sdk-semantic-validator"] = {
            "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
            "required_for": ["calibration probes and deterministic checks must match scorer policy"],
        }


def _append_inventory_v2_constraints(schema: dict[str, Any], filename: str) -> None:
    """Require the typed blocker whenever a v2 value decision needs review."""

    target = (
        schema
        if filename == "package-inventory.v2.schema.json"
        else schema["$defs"]["PackageInventoryRecordV2"]
    )
    target["allOf"] = [
        *target.get("allOf", []),
        {
            "if": {
                "properties": {"value_decision": {"const": "needs_review"}},
                "required": ["value_decision"],
            },
            "then": {
                "properties": {
                    "blocker_codes": {"contains": {"const": "value_review_required"}},
                    "intended_disposition": {"const": "needs_owner_decision"},
                },
                "required": ["blocker_codes", "intended_disposition"],
            },
        },
    ]


def _render_schema(model: type[object], filename: str) -> str:
    schema = model.model_json_schema()  # type: ignore[attr-defined]
    _append_portable_path_constraints(schema)
    if filename == "package-receipt.v1.schema.json":
        # Pydantic emits field types but cannot express the status-dependent
        # receipt invariants enforced by PackageReceipt.model_validator.
        schema["allOf"] = [
            {
                "if": {"properties": {"status": {"const": "built"}}},
                "then": {
                    "required": ["candidate", "package_digest", "manifest", "included_files"],
                    "properties": {
                        "candidate": {"not": {"type": "null"}},
                        "blocker": {"type": "null"},
                        "package_digest": {"not": {"type": "null"}},
                        "manifest": {"not": {"type": "null"}},
                        "included_files": {"minItems": 1},
                    },
                },
            },
            {
                "if": {"properties": {"status": {"const": "blocked"}}},
                "then": {
                    "required": ["blocker"],
                    "properties": {
                        "blocker": {"$ref": "#/$defs/PackageReceiptBlocker"},
                        "package_digest": {"type": "null"},
                    },
                },
            },
        ]
    elif filename == "skill-package-validation.v1.schema.json":
        schema["allOf"] = [
            {
                "if": {"properties": {"status": {"const": "pass"}}, "required": ["status"]},
                "then": {
                    "required": ["candidate", "identity", "files"],
                    "properties": {
                        "candidate": {"not": {"type": "null"}},
                        "identity": {"not": {"type": "null"}},
                        "files": {"minItems": 1},
                        "findings": {
                            "not": {
                                "contains": {
                                    "properties": {"severity": {"const": "blocker"}},
                                    "required": ["severity"],
                                }
                            }
                        },
                    },
                },
            },
            {
                "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
                "then": {
                    "required": ["findings"],
                    "properties": {
                        "findings": {
                            "contains": {
                                "properties": {"severity": {"const": "blocker"}},
                                "required": ["severity"],
                            }
                        }
                    },
                },
            },
        ]
        schema["$comment"] = (
            "Validate candidate/identity package_id binding and file-path uniqueness with "
            "skills_sdk.core.schema_registry.SchemaRegistry.validate; JSON Schema cannot compare arbitrary fields."
        )
        schema["x-skills-sdk-semantic-validator"] = {
            "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
            "required_for": [
                "passing identity package_id must match the candidate package_id",
                "skill validation file paths must be unique",
            ],
        }
    elif filename == "risk-classification.v1.schema.json":
        _append_risk_constraints(schema)
    elif filename == "security-screening.v1.schema.json":
        _append_security_constraints(schema)
    elif filename in {"scenario-set.v1.schema.json", "scorer-profile.v1.schema.json"}:
        _append_evaluation_constraints(schema, filename)
    elif filename in {"package-inventory.v2.schema.json", "package-inventory-set.v2.schema.json"}:
        _append_inventory_v2_constraints(schema, filename)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://schemas.skills-sdk.dev/{filename}"
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or check packaged JSON Schemas.")
    parser.add_argument("--check", action="store_true", help="fail when a committed schema differs from the models")
    args = parser.parse_args()
    schema_root = Path(__file__).resolve().parents[1] / "src/skills_sdk/schemas"
    drift: list[str] = []
    for model, filename in (
        (PackageInventoryRecord, "package-inventory.v1.schema.json"),
        (PackageInventory, "package-inventory-set.v1.schema.json"),
        (PackageInventoryRecordV2, "package-inventory.v2.schema.json"),
        (PackageInventoryV2, "package-inventory-set.v2.schema.json"),
        (PackageCandidateIdentity, "package-candidate.v1.schema.json"),
        (SkillIdentity, "skill-identity.v1.schema.json"),
        (PluginIdentity, "plugin-identity.v1.schema.json"),
        (PackageSource, "package-source.v1.schema.json"),
        (PackageOwner, "package-owner.v1.schema.json"),
        (IntakeDecision, "intake-decision.v1.schema.json"),
        (NormalizedPackage, "normalized-package.v1.schema.json"),
        (PackageManifest, "package-manifest.v1.schema.json"),
        (PackageReceipt, "package-receipt.v1.schema.json"),
        (PackageHardeningReceipt, "package-hardening.v1.schema.json"),
        (RiskClassification, "risk-classification.v1.schema.json"),
        (SecurityScreeningResult, "security-screening.v1.schema.json"),
        (ScenarioSet, "scenario-set.v1.schema.json"),
        (ScorerProfile, "scorer-profile.v1.schema.json"),
        (SkillPackageValidation, "skill-package-validation.v1.schema.json"),
    ):
        rendered = _render_schema(model, filename)
        target = schema_root / filename
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
                drift.append(filename)
        else:
            target.write_text(rendered, encoding="utf-8")
    if drift:
        raise SystemExit(f"schema drift detected: {', '.join(drift)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
