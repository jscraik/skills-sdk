#!/usr/bin/env python3
"""Generate committed JSON Schemas from the public Pydantic contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skills_sdk.models.inventory import PackageInventory, PackageInventoryRecord
from skills_sdk.models.package import (
    IntakeDecision,
    NormalizedPackage,
    PackageCandidateIdentity,
    PackageOwner,
    PackageSource,
    PluginIdentity,
    SkillIdentity,
)
from skills_sdk.models.packaging import PackageManifest, PackageReceipt


def _render_schema(model: type[object], filename: str) -> str:
    schema = model.model_json_schema()  # type: ignore[attr-defined]
    if filename == "package-receipt.v1.schema.json":
        # Pydantic emits field types but cannot express the status-dependent
        # receipt invariants enforced by PackageReceipt.model_validator.
        schema["allOf"] = [
            {
                "if": {"properties": {"status": {"const": "built"}}},
                "then": {
                    "required": ["package_digest", "manifest", "included_files"],
                    "properties": {
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
        (PackageCandidateIdentity, "package-candidate.v1.schema.json"),
        (SkillIdentity, "skill-identity.v1.schema.json"),
        (PluginIdentity, "plugin-identity.v1.schema.json"),
        (PackageSource, "package-source.v1.schema.json"),
        (PackageOwner, "package-owner.v1.schema.json"),
        (IntakeDecision, "intake-decision.v1.schema.json"),
        (NormalizedPackage, "normalized-package.v1.schema.json"),
        (PackageManifest, "package-manifest.v1.schema.json"),
        (PackageReceipt, "package-receipt.v1.schema.json"),
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
