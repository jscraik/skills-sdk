"""Prompt-free read-only portable plugin command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skills_sdk.models.plugin import PluginPackageValidation


def add_plugin_parsers(commands: Any) -> None:
    """Keep plugin-only route registration outside standalone dispatch."""
    from skills_sdk.cli.plugin_presentation import add_parser

    add_plugin_parser(commands)
    add_plugin_normalization_parser(commands)
    add_parser(commands)


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


def add_plugin_normalization_parser(commands: Any) -> None:
    """Register explicit create-only normalization from a standalone skill."""
    parser = commands.add_parser(
        "normalize-plugin", help="copy an admitted standalone skill into a separate complete-plugin candidate"
    )
    parser.add_argument("skill_root", type=Path)
    parser.add_argument("destination_root", type=Path)
    parser.add_argument("--context", required=True, type=Path, help="caller-supplied provenance, rights and owner JSON")
    parser.add_argument("--plugin-name", required=True)
    parser.add_argument("--plugin-version", required=True)
    parser.add_argument("--plugin-description", required=True)
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


def run_plugin_command(
    arguments: argparse.Namespace,
    read_input: Callable[..., bytes],
    pairs: Callable[[list[tuple[str, object]]], dict[str, object]],
) -> int:
    """Dispatch read-only plugin routes with their distinct input-size limits."""
    if arguments.command == "check-plugin-presentation":
        from skills_sdk.cli.plugin_presentation import run

        return run(arguments, read_input)
    if arguments.command == "normalize-plugin":
        return _run_plugin_normalization(arguments, read_input, pairs)
    return run_plugin_validation(arguments, lambda path: read_input(path, max_bytes=16 * 1024 * 1024), pairs)


def _run_plugin_normalization(
    arguments: argparse.Namespace,
    read_input: Callable[[Path], bytes],
    pairs: Callable[[list[tuple[str, object]]], dict[str, object]],
) -> int:
    """Execute explicit candidate creation from a bounded public intake context."""
    from pydantic import ValidationError

    from skills_sdk.intake import normalize_standalone_skill_package
    from skills_sdk.models.intake import SkillPackageIntakeContext
    from skills_sdk.models.plugin_normalization import PluginNormalizationMetadata

    try:
        payload = read_input(arguments.context)
        if len(payload) > 1_048_576:
            raise ValueError("context exceeds the command read budget")
        context = SkillPackageIntakeContext.model_validate(json.loads(payload.decode("utf-8"), object_pairs_hook=pairs))
        metadata = PluginNormalizationMetadata(
            name=arguments.plugin_name,
            version=arguments.plugin_version,
            description=arguments.plugin_description,
        )
    except (OSError, UnicodeDecodeError, ValueError, RecursionError, ValidationError):
        print("normalize-plugin: blocked (invalid intake context or plugin metadata)", file=sys.stderr)
        return 2
    receipt = normalize_standalone_skill_package(
        arguments.skill_root,
        arguments.destination_root,
        context,
        metadata,
    )
    if arguments.json_output:
        print(json.dumps(receipt.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"normalize-plugin: {receipt.status} (candidate preparation only; not release clearance)")
        if receipt.normalized_package is not None:
            print(f"  plugin: {receipt.normalized_package.identity.package_id}")
        if receipt.blocker is not None:
            print(f"  {receipt.blocker.code}: {receipt.blocker.message}")
    return 0 if receipt.status == "prepared" else 2


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
