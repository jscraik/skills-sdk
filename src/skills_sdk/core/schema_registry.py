"""Packaged JSON Schema discovery and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from skills_sdk.core.errors import ContractError

SCHEMA_NAMES = frozenset({"blocker.v1", "package-identity.v1", "receipt-base.v1"})


@dataclass(frozen=True, slots=True)
class SchemaRegistry:
    """Resolve only known, packaged schema versions."""

    def load(self, name: str) -> dict[str, Any]:
        if name not in SCHEMA_NAMES:
            raise ContractError("unknown_schema", f"unsupported schema: {name}")
        resource = files("skills_sdk.schemas").joinpath(f"{name}.schema.json")
        try:
            payload = json.loads(resource.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ContractError("invalid_schema_resource", f"cannot load schema: {name}", (str(error),)) from error
        if not isinstance(payload, dict):
            raise ContractError("invalid_schema_resource", f"schema is not an object: {name}")
        Draft202012Validator.check_schema(payload)
        return payload

    def validate(self, name: str, payload: object) -> None:
        schemas = {schema_name: self.load(schema_name) for schema_name in SCHEMA_NAMES}
        registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
        )
        validator = Draft202012Validator(
            schemas[name],
            format_checker=FormatChecker(),
            registry=registry,
        )
        errors = sorted(validator.iter_errors(payload), key=lambda error: tuple(str(part) for part in error.path))
        if errors:
            details = tuple(error.message for error in errors)
            raise ContractError("contract_validation_failed", f"{name} rejected the payload", details)
