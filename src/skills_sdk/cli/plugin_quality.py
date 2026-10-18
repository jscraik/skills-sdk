"""Bounded JSON inputs for read-only whole-plugin quality composition."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 4_194_304


def _scan_json_structure(text: str) -> None:
    """Bound resources with constant scan state; `json.loads` validates JSON grammar."""
    depth, nodes = 0, 0
    quoted, escaped, scalar = False, False, False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character in " \t\r\n:,":
            scalar = False
            continue
        if character in "]}":
            depth -= 1
            scalar = False
            if depth < 0:
                raise ValueError("unbalanced JSON container")
            continue
        if character in "[{":
            depth += 1
            scalar = False
            if depth > _MAX_JSON_DEPTH:
                raise ValueError("JSON nesting exceeds the structural limit")
        elif character == '"':
            quoted = True
            scalar = False
        elif scalar:
            continue
        else:
            scalar = True
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise ValueError("JSON node count exceeds the structural limit")
    if quoted or depth:
        raise ValueError("unterminated JSON string or container")


def _load_json(
    read_input: Callable[..., bytes], path: Path, pairs: Callable[..., object], limit: dict[str, int]
) -> Any:
    """Read no-follow bytes, scan structure, then materialize with duplicate-member rejection."""
    text = read_input(path, **limit).decode("utf-8")
    _scan_json_structure(text)
    return json.loads(text, object_pairs_hook=pairs)


def add_parser(commands: Any) -> None:
    """Register an additive route without changing standalone quality behavior."""
    parser = commands.add_parser("check-plugin-quality", help="compose local child quality and plugin presentation")
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--assessments", type=Path)
    parser.add_argument("--presentation-request", type=Path)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--robot", action="store_true")


def run(arguments: argparse.Namespace, read_input: Callable[..., bytes], pairs: Callable[..., object]) -> int:
    """Reject unsafe input files and preserve typed first-stop receipts."""
    from skills_sdk.evaluation.plugin_quality import check_plugin_quality
    from skills_sdk.models.plugin_quality import PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES, PluginQualityResult

    try:
        inputs = {
            name: _load_json(read_input, path, pairs, limit) if path else None
            for name, path, limit in (
                ("request", arguments.request, {}),
                ("assessments", arguments.assessments, {"max_bytes": PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES}),
                ("presentation_request", arguments.presentation_request, {}),
            )
        }
    except (OSError, ValueError, RecursionError):
        result = PluginQualityResult.model_validate(
            {
                "status": "blocked",
                "blocker": {
                    "code": "plugin_quality_input_invalid",
                    "message": "Inputs require bounded no-follow JSON.",
                },
            }
        )
    else:
        result = asyncio.run(check_plugin_quality(arguments.plugin_root, **inputs))
    if arguments.json_output:
        print(result.model_dump_json())
    else:
        print(f"check-plugin-quality: {result.status}")
        if result.blocker:
            print(f"  {result.blocker.code}: {result.blocker.message}")
    return 0 if result.status == "local_checks_passed" else 2
