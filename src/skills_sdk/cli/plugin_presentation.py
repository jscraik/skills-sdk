"""Prompt-free presentation assessment with no mutation or release authority."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Expose the fixed read-only icon profile without changing portable intake."""
    parser = commands.add_parser("check-plugin-presentation", help="check captured assets and supplied bound approvals")
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--robot", action="store_true", help="prompt-free; never grants external authority")


def run(arguments: argparse.Namespace, read_input: Callable[[Path], bytes]) -> int:
    """Read a bounded ordinary no-follow JSON file and emit a versioned result."""
    from skills_sdk.models.plugin_presentation import PluginPresentationCheck
    from skills_sdk.models.validation import SkillPackageFinding, ValidationSeverity
    from skills_sdk.validation.plugin_manifest import _object
    from skills_sdk.validation.plugin_presentation import check_plugin_presentation

    try:
        payload = _object(read_input(arguments.request))
        result = check_plugin_presentation(
            arguments.plugin_root, source_revision=arguments.source_revision, request=payload
        )
    except (OSError, ValueError, TypeError, RecursionError):
        result = PluginPresentationCheck(
            status="blocked",
            findings=(
                SkillPackageFinding(
                    code="plugin_presentation_input_invalid",
                    severity=ValidationSeverity.BLOCKER,
                    message="request must be a bounded regular no-follow JSON object without duplicate members",
                ),
            ),
        )
    if arguments.json_output:
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"check-plugin-presentation: {result.status} (supplied approvals; not release or host-display clearance)")
        for item in result.findings:
            print(f"  {item.code}: {item.message}")
    return 0 if result.status == "pass" else 2
