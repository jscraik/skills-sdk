from __future__ import annotations

from typing import Any


def append_selected_case_constraints(schema: dict[str, Any], filename: str, credential_pattern: str) -> None:
    """Project credential-safe judge evidence refs into the packaged schema."""

    if filename != "selected-case-judge-evidence.v1.schema.json":
        return
    schema["properties"]["evidence_refs"]["items"]["not"] = {"pattern": credential_pattern}
