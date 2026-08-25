#!/usr/bin/env python3
"""Generate committed JSON Schemas from the public Pydantic contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skills_sdk.models.inventory import PackageInventory, PackageInventoryRecord


def _render_schema(model: type[object], filename: str) -> str:
    schema = model.model_json_schema()  # type: ignore[attr-defined]
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
