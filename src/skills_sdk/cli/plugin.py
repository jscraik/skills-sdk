"""Prompt-free read-only portable plugin command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def add_plugin_parser(commands: Any) -> None:
    """Register a distinct route; standalone validate/build keep their meanings."""
    parser = commands.add_parser("validate-plugin", help="capture and validate a portable root-manifest plugin")
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--require-version", action="store_true", help="apply SDK nonempty-version metadata policy")
    parser.add_argument(
        "--require-description", action="store_true", help="apply SDK nonempty-description metadata policy"
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")


def run_plugin_validation(arguments: argparse.Namespace) -> int:
    """Emit a typed result without publication, installation or execution."""
    from skills_sdk.models.plugin import PluginValidationPolicy
    from skills_sdk.validation.plugin_package import validate_plugin_package

    result = validate_plugin_package(
        arguments.plugin_root,
        source_revision=arguments.source_revision,
        policy=PluginValidationPolicy(
            require_version=arguments.require_version, require_description=arguments.require_description
        ),
    )
    if arguments.json_output:
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"validate-plugin: {result.status} (structural capture only; not release clearance)")
        for item in result.findings:
            print(f"  {item.code}: {item.message}")
        for child in result.skills:
            print(f"  {child.path}: {child.validation.status}")
            for finding in child.validation.findings:
                print(f"    {finding.code}: {finding.message}")
    return 0 if result.status == "pass" else 2
