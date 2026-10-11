"""Draft 2020-12 projections for the additive safety-admission evidence family."""

from typing import Any

from package_safety_schema import MACHINE_PATH_SCHEMA_PATTERN, PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN

from skills_sdk.models.pre_execution_safety import SAFETY_CHECK_IDS

_NONBLANK_RATIONALE_PATTERN = (
    r"[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a"
    r"\u2028\u2029\u202f\u205f\u3000]"
)
_RATIONALE_CREDENTIAL_PATTERN = PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN.replace(r"\s", r"\u0009-\u000d ")


def append_pre_execution_safety_constraints(schema: dict[str, Any]) -> None:
    """Project checklist shape/privacy and label remaining semantic joins."""
    schema["properties"]["checklist"].update(
        minItems=len(SAFETY_CHECK_IDS),
        maxItems=len(SAFETY_CHECK_IDS),
        items=False,
        prefixItems=[
            {
                "$ref": "#/$defs/CapabilitySafetyReview",
                "properties": {"check_id": {"const": check_id}},
            }
            for check_id in SAFETY_CHECK_IDS
        ],
    )
    properties = schema["$defs"]["CapabilitySafetyReview"]["properties"]
    properties["evidence_ids"]["uniqueItems"] = True
    properties["rationale"].setdefault("allOf", []).extend(
        (
            {"pattern": _NONBLANK_RATIONALE_PATTERN},
            {"not": {"pattern": _RATIONALE_CREDENTIAL_PATTERN}},
            {"not": {"pattern": MACHINE_PATH_SCHEMA_PATTERN}},
        )
    )
    schema["$comment"] = (
        "Validate digest and cross-object bindings, applicable capability outcomes, and supported "
        "completed screening with skills_sdk.core.schema_registry.SchemaRegistry.validate."
    )
    schema["x-skills-sdk-semantic-validator"] = {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": [
            "package, review and screening must bind the same candidate and captured manifest",
            "screening and checklist digests must match retained review evidence",
            "checklist evidence ids must resolve to supplied review evidence",
            "screening must be completed by the supported sensor and applicable checks reviewed",
        ],
    }
