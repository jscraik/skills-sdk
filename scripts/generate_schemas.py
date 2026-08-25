#!/usr/bin/env python3
"""Generate committed JSON Schemas from the public Pydantic contracts."""

from __future__ import annotations

import json
from pathlib import Path

from skills_sdk.models.inventory import PackageInventory, PackageInventoryRecord


def main() -> None:
    schema_root = Path(__file__).resolve().parents[1] / "src/skills_sdk/schemas"
    for model, filename in (
        (PackageInventoryRecord, "package-inventory.v1.schema.json"),
        (PackageInventory, "package-inventory-set.v1.schema.json"),
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://schemas.skills-sdk.dev/{filename}"
        (schema_root / filename).write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
