#!/usr/bin/env python3
"""Generate committed JSON Schemas from the public Pydantic contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import package_safety_schema
from package_archive_schema import append_package_archive_constraints
from provider_execution_schema import append_provider_execution_constraints
from runtime_lifecycle_schema import append_runtime_lifecycle_constraints
from schema_model_groups import (
    evaluation_schema_models,
    packaging_schema_models,
    provider_execution_schema_models,
    runtime_lifecycle_schema_models,
)

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
from skills_sdk.models.provider import ProviderIdentity, ProviderIdentityV2
from skills_sdk.models.registry import (
    REGISTRY_PACKAGE_NAME_MAX_LENGTH,
    REGISTRY_VERSION_PATTERN,
    RegistryIdentity,
    RegistryPreparationReceipt,
    RegistryPreparationRequest,
)
from skills_sdk.models.risk import RiskClassification, SecurityScreeningResult
from skills_sdk.models.safety import PackageSafetyEvidenceReceipt
from skills_sdk.models.validation import SkillPackageValidation

_PORTABLE_PATH_PATTERN = (
    r"^(?=.*\S)(?!.*[\r\n])(?!/)(?!.*\\)(?!.*(?:^|/)\.\.?(?:/|$))(?![^/]*:)"
    r"(?!.*//)(?!.*(?:^|/)\./)(?!.*\/$)[\s\S]+$"
)
_NON_WHITESPACE_TEXT_PATTERN = r"^[\s\S]*\S[\s\S]*$"
_NORMALIZED_TEXT_PATTERN = r"^\S(?:[\s\S]*\S)?$"
_PROVIDER_IDENTITY_FIELDS = ("provider_id", "model_id", "version_or_digest", "adapter_id", "adapter_version_or_digest")
_REGISTRY_IDENTITY_FIELDS = ("registry_id", "namespace")
_REGISTRY_PUBLIC_CREDENTIAL_SCHEMA_PATTERN = (
    r"(^|[^A-Za-z0-9])(?:[aA][iI][zZ][aA]|[aA][kK][iI][aA]|[bB][eE][aA][rR][eE][rR]|[gG][hH][pP]_|"
    r"[gG][iI][tT][hH][uU][bB]_[pP][aA][tT]_|[hH][fF]_|[sS][kK]-|[xX][oO][xX][bB]-|[xX][oO][xX][pP]-)"
)
_V1_CREDENTIAL_COMPONENT_SCHEMA_PATTERN = (
    r"(^|[._:+-])(?:[aA][kK][iI][aA]|[bB][eE][aA][rR][eE][rR]|[gG][hH][pP]_|"
    r"[gG][iI][tT][hH][uU][bB]_[pP][aA][tT]_|[sS][kK]-|[xX][oO][xX][bB]-|[xX][oO][xX][pP]-)"
)
_REGISTRY_CREDENTIAL_COMPONENT_SCHEMA_PATTERN = (
    r"(^|[._:+-])(?:[aA][iI][zZ][aA]|[aA][kK][iI][aA]|[bB][eE][aA][rR][eE][rR]|[gG][hH][pP]_|"
    r"[gG][iI][tT][hH][uU][bB]_[pP][aA][tT]_|[hH][fF]_|[sS][kK]-|[xX][oO][xX][bB]-|[xX][oO][xX][pP]-)"
)
_V2_CREDENTIAL_COMPONENT_SCHEMA_PATTERN = (
    r"(^|[._:+/-])(?:[aA][iI][zZ][aA]|[aA][kK][iI][aA]|[bB][eE][aA][rR][eE][rR]|[gG][hH][pP]_|"
    r"[gG][iI][tT][hH][uU][bB]_[pP][aA][tT]_|[hH][fF]_|[sS][kK]-|[xX][oO][xX][bB]-|[xX][oO][xX][pP]-)"
)
_MODEL_ID_URI_SCHEME_SCHEMA_PATTERN = r"^[A-Za-z][A-Za-z0-9+.-]*:"


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


def _append_provider_identity_constraints(schema: Any) -> None:
    """Project the secret-free contract into standalone and nested provider schemas."""

    if isinstance(schema, dict):
        title = schema.get("title")
        if title == "ProviderIdentity":
            properties = schema.get("properties", {})
            for field in _PROVIDER_IDENTITY_FIELDS:
                properties[field]["not"] = {"pattern": _V1_CREDENTIAL_COMPONENT_SCHEMA_PATTERN}
        elif title == "ProviderIdentityV2":
            properties = schema.get("properties", {})
            for field in _PROVIDER_IDENTITY_FIELDS:
                properties[field]["not"] = {"pattern": _V2_CREDENTIAL_COMPONENT_SCHEMA_PATTERN}
            properties["model_id"].setdefault("allOf", []).append(
                {"not": {"pattern": _MODEL_ID_URI_SCHEME_SCHEMA_PATTERN}}
            )
        for value in schema.values():
            _append_provider_identity_constraints(value)
    elif isinstance(schema, list):
        for value in schema:
            _append_provider_identity_constraints(value)


def _append_registry_identity_constraints(schema: Any) -> None:
    """Project the secret-free contract into registry identity schemas."""

    if isinstance(schema, dict):
        title = schema.get("title")
        if title == "RegistryIdentity":
            properties = schema.get("properties", {})
            for field in _REGISTRY_IDENTITY_FIELDS:
                properties[field]["not"] = {"pattern": _REGISTRY_CREDENTIAL_COMPONENT_SCHEMA_PATTERN}
        elif title in {"RegistryPreparationRequest", "RegistryPreparationReceipt"}:
            properties = schema["properties"]
            for field in ("package_name", "version"):
                properties[field]["not"] = {"pattern": _REGISTRY_PUBLIC_CREDENTIAL_SCHEMA_PATTERN}
            properties["version"]["pattern"] = _NORMALIZED_TEXT_PATTERN
            if title == "RegistryPreparationRequest":
                properties["evidence"]["uniqueItems"] = True
            properties["evidence"]["items"]["not"] = {"pattern": _REGISTRY_PUBLIC_CREDENTIAL_SCHEMA_PATTERN}
        elif title == "RegistryPreparationBlocker":
            for field in ("code", "message"):
                schema["properties"][field]["not"] = {"pattern": _REGISTRY_PUBLIC_CREDENTIAL_SCHEMA_PATTERN}
            schema["properties"]["evidence_refs"]["items"]["not"] = {
                "pattern": _REGISTRY_PUBLIC_CREDENTIAL_SCHEMA_PATTERN
            }
        elif title == "RegistryPreparationWarning":
            schema["properties"]["evidence_refs"]["items"]["not"] = {
                "pattern": _REGISTRY_PUBLIC_CREDENTIAL_SCHEMA_PATTERN
            }
        for value in schema.values():
            _append_registry_identity_constraints(value)
    elif isinstance(schema, list):
        for value in schema:
            _append_registry_identity_constraints(value)


def _append_registry_preparation_constraints(schema: dict[str, Any]) -> None:
    """Project JSON-Schema-expressible registry receipt invariants."""

    properties = schema["properties"]
    properties["evidence"]["uniqueItems"] = True
    schema["$defs"]["RegistryPreparationBlocker"]["properties"]["evidence_refs"]["uniqueItems"] = True
    properties["warnings"]["items"] = {"$ref": "#/$defs/RegistryPreparationWarning"}
    schema["$defs"]["RegistryPreparationWarning"]["properties"]["evidence_refs"]["uniqueItems"] = True
    digest_properties = {
        "hardening_receipt_sha256": {"type": "string"},
        "manifest_digest": {"type": "string"},
        "package_digest": {"type": "string"},
    }
    schema["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "prepared"}}, "required": ["status"]},
            "then": {
                "required": ["candidate", "hardening_receipt_sha256", "manifest_digest", "package_digest"],
                "properties": {
                    "blocker": {"type": "null"},
                    "blockers": {"maxItems": 0},
                    "candidate": {"$ref": "#/$defs/PackageCandidateIdentity"},
                    "package_name": {"maxLength": REGISTRY_PACKAGE_NAME_MAX_LENGTH},
                    "version": {"pattern": REGISTRY_VERSION_PATTERN},
                    **digest_properties,
                },
            },
        },
        {
            "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
            "then": {
                "required": ["blocker", "blockers"],
                "properties": {
                    "blocker": {"$ref": "#/$defs/RegistryPreparationBlocker"},
                    "blockers": {"items": {"$ref": "#/$defs/RegistryPreparationBlocker"}, "minItems": 1},
                    "hardening_receipt_sha256": {"type": "null"},
                    "manifest_digest": {"type": "null"},
                    "package_digest": {"type": "null"},
                },
            },
        },
    ]
    schema["$comment"] = (
        "Validate candidate, package-name, digest, warning, and evidence binding with "
        "skills_sdk.core.schema_registry.SchemaRegistry.validate."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": [
            "package name must match candidate package_id",
            "package and manifest digests must match",
            "registry preparation evidence paths must be unique",
            "blocked registry receipt must retain its primary blocker first",
        ],
    }


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
            },
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
                    },
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

    if filename in {"scenario-set.v1.schema.json", "scenario-set.v2.schema.json"}:
        case_name = "ScenarioCase" if filename.endswith("v1.schema.json") else "ScenarioCaseV2"
        scenario_case_properties = schema["$defs"][case_name]["properties"]
        scenario_case_properties["case_id"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        scenario_case_properties["prompt"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        scenario_case_properties["expected_signals"]["items"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        scenario_case_properties["forbidden_commands"]["items"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        schema["properties"]["scenario_set_id"]["pattern"] = _NON_WHITESPACE_TEXT_PATTERN
        schema["properties"]["cases"]["items"]["$ref"] = f"#/$defs/{case_name}"
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


def _append_evaluation_result_constraints(schema: dict[str, Any], filename: str) -> None:
    """Project result status invariants while marking model-only comparisons."""

    properties = schema["properties"]
    properties["evidence_refs"]["uniqueItems"] = True
    if filename in {"scenario-observation.v1.schema.json", "scenario-observation.v2.schema.json"}:
        schema["allOf"] = [
            {
                "if": {"properties": {"status": {"const": "completed"}}, "required": ["status"]},
                "then": {
                    "required": ["output_sha256"],
                    "properties": {"blocker": {"type": "null"}, "output_sha256": {"type": "string"}},
                },
            },
            {
                "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
                "then": {
                    "required": ["blocker"],
                    "properties": {
                        "blocker": {"$ref": "#/$defs/PackageReceiptBlocker"},
                        "observed_commands": {"maxItems": 0},
                        "observed_signals": {"maxItems": 0},
                        "output_sha256": {"type": "null"},
                    },
                },
            },
        ]
        required_for = ["scenario observation evidence refs must be unique"]
    else:
        schema["allOf"] = [
            {
                "if": {"properties": {"status": {"const": "pass"}}, "required": ["status"]},
                "then": {
                    "required": ["observation_sha256"],
                    "properties": {
                        "blocker": {"type": "null"},
                        "forbidden_commands_observed": {"maxItems": 0},
                        "missing_signals": {"maxItems": 0},
                        "observation_sha256": {"type": "string"},
                    },
                },
            },
            {
                "if": {"properties": {"status": {"const": "fail"}}, "required": ["status"]},
                "then": {
                    "required": ["observation_sha256"],
                    "properties": {
                        "blocker": {"type": "null"},
                        "observation_sha256": {"type": "string"},
                    },
                    "anyOf": [
                        {"properties": {"missing_signals": {"minItems": 1}}, "required": ["missing_signals"]},
                        {
                            "properties": {"forbidden_commands_observed": {"minItems": 1}},
                            "required": ["forbidden_commands_observed"],
                        },
                        *(
                            [
                                {
                                    "properties": {"output_digest_mismatch": {"const": True}},
                                    "required": ["output_digest_mismatch"],
                                }
                            ]
                            if filename == "scenario-case-result.v2.schema.json"
                            else []
                        ),
                    ],
                },
            },
            {
                "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
                "then": {
                    "required": ["blocker"],
                    "properties": {
                        "blocker": {"$ref": "#/$defs/PackageReceiptBlocker"},
                        "observation_sha256": {"type": "null"},
                    },
                },
            },
        ]
        required_for = ["scenario result evidence refs and case ids must be unique"]
    schema["$comment"] = (
        "Validate candidate, scenario-set, and identifier binding with "
        "skills_sdk.core.schema_registry.SchemaRegistry.validate."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": required_for,
    }


def _append_evaluation_receipt_constraints(schema: dict[str, Any], filename: str) -> None:
    """Project receipt status invariants and mark cross-object model checks."""

    properties = schema["properties"]
    properties["case_results"]["uniqueItems"] = True
    properties["completed_calibration_probe_ids"]["uniqueItems"] = True
    completed = {
        "required": ["score", "case_results"],
        "properties": {
            "blocker": {"type": "null"},
            "case_results": {"minItems": 1},
            "score": {"type": "number"},
        },
    }
    schema["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "pass"}}, "required": ["status"]},
            "then": completed,
        },
        {
            "if": {"properties": {"status": {"const": "fail"}}, "required": ["status"]},
            "then": completed,
        },
        {
            "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
            "then": {
                "properties": {"score": {"type": "null"}},
                "anyOf": [
                    {
                        "properties": {"blocker": {"$ref": "#/$defs/PackageReceiptBlocker"}},
                        "required": ["blocker"],
                    },
                    {
                        "properties": {
                            "case_results": {
                                "contains": {
                                    "properties": {"status": {"const": "blocked"}},
                                    "required": ["status"],
                                }
                            }
                        },
                        "required": ["case_results"],
                    },
                ],
            },
        },
    ]
    if filename == "evaluation-receipt.v2.schema.json":
        schema["allOf"].append(
            {
                "if": {"properties": {"case_results": {"minItems": 1}}, "required": ["case_results"]},
                "then": {"properties": {"provider": {"not": {"type": "null"}}}, "required": ["provider"]},
            }
        )
    schema["$comment"] = (
        "Validate candidate, scorer, case-result, calibration, threshold, and identifier binding with "
        "skills_sdk.core.schema_registry.SchemaRegistry.validate."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": [
            "evaluation case ids must be unique",
            "completed calibration probes must match scorer policy",
            "receipt status must match the scorer threshold",
        ],
    }
    if filename == "evaluation-receipt.v2.schema.json":
        schema["x-skills-sdk-semantic-validator"]["required_for"].append(
            "a receipt retaining case results must bind one provider"
        )


def _append_inventory_v2_constraints(schema: dict[str, Any], filename: str) -> None:
    """Require the typed blocker whenever a v2 value decision needs review."""

    target = schema if filename == "package-inventory.v2.schema.json" else schema["$defs"]["PackageInventoryRecordV2"]
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


def _render_schema(model: type[package_safety_schema.SchemaModel], filename: str) -> str:
    schema = model.model_json_schema()
    _append_portable_path_constraints(schema)
    _append_provider_identity_constraints(schema)
    _append_registry_identity_constraints(schema)
    package_safety_schema.append_package_safety_schema_constraints(schema, filename)
    if filename in {"package-receipt.v1.schema.json", "package-receipt.v2.schema.json"}:
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
    elif filename in {"scenario-set.v1.schema.json", "scenario-set.v2.schema.json", "scorer-profile.v1.schema.json"}:
        _append_evaluation_constraints(schema, filename)
    elif filename in {
        "scenario-observation.v1.schema.json",
        "scenario-observation.v2.schema.json",
        "scenario-case-result.v1.schema.json",
        "scenario-case-result.v2.schema.json",
    }:
        _append_evaluation_result_constraints(schema, filename)
    elif filename in {"evaluation-receipt.v1.schema.json", "evaluation-receipt.v2.schema.json"}:
        _append_evaluation_receipt_constraints(schema, filename)
    elif filename in {"package-inventory.v2.schema.json", "package-inventory-set.v2.schema.json"}:
        _append_inventory_v2_constraints(schema, filename)
    elif filename == "package-archive-verification.v1.schema.json":
        append_package_archive_constraints(schema)
    elif filename == "registry-preparation.v1.schema.json":
        _append_registry_preparation_constraints(schema)
    elif filename in {"provider-execution-request.v1.schema.json", "provider-execution-result.v1.schema.json"}:
        append_provider_execution_constraints(schema, filename)
    elif filename in {
        "runtime-lock.v1.schema.json",
        "install-plan.v1.schema.json",
        "installation-result.v1.schema.json",
        "rollback-journal.v1.schema.json",
        "rollback-outcome.v1.schema.json",
        "discovery-observation.v1.schema.json",
        "activation-observation.v1.schema.json",
        "runtime-outcome.v1.schema.json",
    }:
        append_runtime_lifecycle_constraints(schema, filename)
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
        *packaging_schema_models(),
        (ProviderIdentity, "provider-identity.v1.schema.json"),
        (ProviderIdentityV2, "provider-identity.v2.schema.json"),
        (RegistryIdentity, "registry-identity.v1.schema.json"),
        (RegistryPreparationReceipt, "registry-preparation.v1.schema.json"),
        (RegistryPreparationRequest, "registry-preparation-request.v1.schema.json"),
        (PackageSafetyEvidenceReceipt, "package-safety-evidence.v1.schema.json"),
        (RiskClassification, "risk-classification.v1.schema.json"),
        (SecurityScreeningResult, "security-screening.v1.schema.json"),
        *evaluation_schema_models(),
        *provider_execution_schema_models(),
        *runtime_lifecycle_schema_models(),
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
