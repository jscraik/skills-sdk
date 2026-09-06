"""Generated JSON Schema constraints for package archive verification."""

from __future__ import annotations

from typing import Any


def append_package_archive_constraints(schema: dict[str, Any]) -> None:
    """Add state constraints that Pydantic cannot project into JSON Schema."""

    properties = schema["properties"]
    properties["verified_files"]["uniqueItems"] = True
    schema["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "pass"}}, "required": ["status"]},
            "then": {
                "required": ["archive_sha256", "candidate", "package_digest", "manifest", "verified_files"],
                "properties": {
                    "archive_sha256": {"type": "string"},
                    "candidate": {"$ref": "#/$defs/PackageCandidateIdentity"},
                    "package_digest": {"type": "string"},
                    "manifest": {"$ref": "#/$defs/PackageManifest"},
                    "verified_files": {"minItems": 1},
                    "blocker": {"type": "null"},
                },
            },
        },
        {
            "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
            "then": {
                "required": ["blocker"],
                "properties": {
                    "archive_sha256": {"type": "null"},
                    "candidate": {"type": "null"},
                    "package_digest": {"type": "null"},
                    "manifest": {"type": "null"},
                    "verified_files": {"maxItems": 0},
                    "blocker": {"$ref": "#/$defs/PackageReceiptBlocker"},
                },
            },
        },
    ]
    schema["$comment"] = (
        "Validate digest, candidate, manifest, and verified-file equality with "
        "skills_sdk.core.schema_registry.SchemaRegistry.validate."
    )


__all__ = ["append_package_archive_constraints"]
