from __future__ import annotations

from typing import Any

from package_safety_schema import MACHINE_PATH_SCHEMA_PATTERN, PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN

_NORMALIZED_TEXT_PATTERN = r"^\S(?:[\s\S]*\S)?$"


def append_selected_case_constraints(schema: dict[str, Any], filename: str) -> None:
    """Project credential-safe judge evidence refs into the packaged schema."""

    if filename != "selected-case-judge-evidence.v1.schema.json":
        return
    schema["properties"]["evidence_refs"]["items"].setdefault("allOf", []).extend(
        (
            {"not": {"pattern": PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN}},
            {"not": {"pattern": MACHINE_PATH_SCHEMA_PATTERN}},
        )
    )
    schema["properties"]["evidence_refs"]["uniqueItems"] = True
    schema["properties"]["satisfied_assertion_ids"]["uniqueItems"] = True
    schema["$defs"]["PackageCandidateIdentity"]["properties"]["package_id"].setdefault("allOf", []).append(
        {"not": {"pattern": PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN}}
    )
    for field in ("case_id", "scenario_set_id"):
        schema["properties"][field].setdefault("allOf", []).extend(
            (
                {"pattern": _NORMALIZED_TEXT_PATTERN},
                {"not": {"pattern": PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN}},
                {"not": {"pattern": MACHINE_PATH_SCHEMA_PATTERN}},
            )
        )
    schema["properties"]["satisfied_assertion_ids"]["items"].setdefault("allOf", []).extend(
        (
            {"pattern": _NORMALIZED_TEXT_PATTERN},
            {"not": {"pattern": PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN}},
            {"not": {"pattern": MACHINE_PATH_SCHEMA_PATTERN}},
        )
    )
