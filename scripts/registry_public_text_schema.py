"""Registry public-text constraints shared by generated schema families."""

from __future__ import annotations

from typing import Any

import package_safety_schema

_REGISTRY_PUBLIC_CREDENTIAL_SCHEMA_PATTERN = (
    r"(^|[^A-Za-z0-9])(?:[aA][iI][zZ][aA]|[aA][kK][iI][aA]|[bB][eE][aA][rR][eE][rR]|[gG][hH][pP]_|"
    r"[gG][iI][tT][hH][uU][bB]_[pP][aA][tT]_|[hH][fF]_|[sS][kK]-|[xX][oO][xX][bB]-|[xX][oO][xX][pP]-)"
)
_REGISTRY_CREDENTIAL_COMPONENT_SCHEMA_PATTERN = (
    r"(^|[._:+-])(?:[aA][iI][zZ][aA]|[aA][kK][iI][aA]|[bB][eE][aA][rR][eE][rR]|[gG][hH][pP]_|"
    r"[gG][iI][tT][hH][uU][bB]_[pP][aA][tT]_|[hH][fF]_|[sS][kK]-|[xX][oO][xX][bB]-|[xX][oO][xX][pP]-)"
)
_REGISTRY_PUBLIC_TEXT_SCHEMA_DEFINITION = {
    "allOf": [
        {"not": {"pattern": package_safety_schema.PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN}},
        {"not": {"pattern": package_safety_schema.MACHINE_PATH_SCHEMA_PATTERN}},
    ]
}
_REGISTRY_PUBLIC_TEXT_SCHEMA_FILENAMES = {
    "registry-preparation-request.v1.schema.json",
    "registry-preparation.v1.schema.json",
}
_NORMALIZED_TEXT_PATTERN = r"^\S(?:[\s\S]*\S)?$"


def _append_registry_public_text_constraint(property_schema: dict[str, Any], filename: str) -> None:
    if filename in _REGISTRY_PUBLIC_TEXT_SCHEMA_FILENAMES:
        property_schema.setdefault("allOf", []).append({"$ref": "#/$defs/RegistryPublicText"})
    else:
        property_schema["not"] = {"pattern": _REGISTRY_PUBLIC_CREDENTIAL_SCHEMA_PATTERN}


def append_registry_identity_constraints(
    schema: Any,
    filename: str,
    root_schema: dict[str, Any] | None = None,
) -> None:
    """Project secret-free registry constraints into generated schemas."""
    if isinstance(schema, dict):
        if root_schema is None:
            root_schema = schema
        if schema is root_schema and filename in _REGISTRY_PUBLIC_TEXT_SCHEMA_FILENAMES:
            root_schema.setdefault("$defs", {})["RegistryPublicText"] = _REGISTRY_PUBLIC_TEXT_SCHEMA_DEFINITION
        title = schema.get("title")
        if title == "RegistryIdentity":
            properties = schema.get("properties", {})
            for field in ("registry_id", "namespace"):
                properties[field]["not"] = {"pattern": _REGISTRY_CREDENTIAL_COMPONENT_SCHEMA_PATTERN}
        elif title in {"RegistryPreparationRequest", "RegistryPreparationReceipt"}:
            properties = schema["properties"]
            for field in ("package_name", "version"):
                _append_registry_public_text_constraint(properties[field], filename)
            properties["version"]["pattern"] = _NORMALIZED_TEXT_PATTERN
            if title == "RegistryPreparationRequest":
                properties["evidence"]["uniqueItems"] = True
            _append_registry_public_text_constraint(properties["evidence"]["items"], filename)
        elif title == "RegistryPreparationBlocker":
            for field in ("code", "message"):
                _append_registry_public_text_constraint(schema["properties"][field], filename)
            _append_registry_public_text_constraint(schema["properties"]["evidence_refs"]["items"], filename)
        elif title == "RegistryPreparationWarning":
            _append_registry_public_text_constraint(schema["properties"]["evidence_refs"]["items"], filename)
        for value in schema.values():
            append_registry_identity_constraints(value, filename, root_schema)
    elif isinstance(schema, list):
        for value in schema:
            append_registry_identity_constraints(value, filename, root_schema)
