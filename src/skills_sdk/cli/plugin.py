"""Prompt-free read-only portable plugin command."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skills_sdk.models.plugin import PluginPackageValidation


def add_plugin_parser(commands: Any) -> None:
    """Register a distinct route; standalone validate/build keep their meanings."""
    parser = commands.add_parser("validate-plugin", help="capture and validate a portable root-manifest plugin")
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument(
        "--verify-evidence", type=Path, help="compare supplied validation JSON with a fresh source capture"
    )
    parser.add_argument("--require-version", action="store_true", help="apply SDK nonempty-version metadata policy")
    parser.add_argument(
        "--require-description", action="store_true", help="apply SDK nonempty-description metadata policy"
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")


def _validation_result(
    arguments: argparse.Namespace,
    read_input: Callable[[Path], bytes],
    pairs: Callable[[list[tuple[str, object]]], dict[str, object]],
) -> PluginPackageValidation:
    """Recheck supplied evidence against source without echoing private settings."""
    from skills_sdk.models.plugin import PluginPackageValidation, PluginValidationPolicy
    from skills_sdk.models.validation import SkillPackageFinding, ValidationSeverity
    from skills_sdk.validation.plugin_evidence import verify_plugin_package_validation
    from skills_sdk.validation.plugin_package import validate_plugin_package

    policy = PluginValidationPolicy(
        require_version=arguments.require_version, require_description=arguments.require_description
    )
    if arguments.verify_evidence is None:
        return validate_plugin_package(arguments.plugin_root, source_revision=arguments.source_revision, policy=policy)
    try:
        evidence = json.loads(read_input(arguments.verify_evidence).decode("utf-8"), object_pairs_hook=pairs)
    except (OSError, ValueError, RecursionError):
        return PluginPackageValidation(
            status="blocked",
            policy=policy,
            findings=(
                SkillPackageFinding(
                    code="plugin_evidence_invalid",
                    severity=ValidationSeverity.BLOCKER,
                    message="supplied plugin evidence requires bounded no-follow JSON",
                ),
            ),
        )
    return verify_plugin_package_validation(
        arguments.plugin_root, evidence, source_revision=arguments.source_revision, policy=policy
    )


def run_plugin_validation(
    arguments: argparse.Namespace,
    read_input: Callable[[Path], bytes],
    pairs: Callable[[list[tuple[str, object]]], dict[str, object]],
) -> int:
    """Emit a typed result without publication, installation or execution."""
    result = _validation_result(arguments, read_input, pairs)
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
