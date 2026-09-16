from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from skills_sdk import __version__

COMMAND_HELP = {
    "inventory": "inspect a read-only source inventory",
    "intake": "reserved read-only package intake and normalization contract",
    "validate": "run package contract validation",
    "build": "build an immutable package candidate",
    "eval": "run candidate-bound evaluation lanes",
    "package": "prepare a distributable package",
    "project": "project a candidate into a selected runtime surface",
    "verify": "verify candidate-bound evidence",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="skills-sdk",
        description="Portable lifecycle contracts and tooling for Agent Skills packages.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", title="commands")
    for name, help_text in COMMAND_HELP.items():
        if name in {"validate", "build", "eval"}:
            continue
        commands.add_parser(name, help=help_text, description=help_text)
    compare = commands.add_parser("compare-copy", help="compare validated source and runtime file bytes without writes")
    compare.add_argument("source_root", type=Path)
    compare.add_argument("runtime_root", type=Path)
    compare.add_argument("--source-revision", required=True)
    compare.add_argument("--json", action="store_true", dest="json_output")
    maintenance = commands.add_parser(
        "maintain-entrypoint", help="check or repair an existing skill entrypoint or sibling document"
    )
    maintenance.add_argument("source", type=Path)
    maintenance.add_argument("target", type=Path)
    maintenance.add_argument("--backup-root", type=Path, required=True)
    maintenance.add_argument("--expected-source", required=True)
    maintenance.add_argument("--expected-current", required=True)
    maintenance.add_argument(
        "--supporting-document", action="store_true", help="maintain an existing sibling Markdown document"
    )
    maintenance.add_argument("--apply", action="store_true", help="apply the separately authorized repair")
    maintenance.add_argument("--json", action="store_true", dest="json_output")
    for name in ("validate", "build"):
        command = commands.add_parser(name, help=COMMAND_HELP[name], description=COMMAND_HELP[name])
        command.add_argument("package_root", type=Path)
        command.add_argument("--source-revision")
        command.add_argument("--max-entrypoint-lines", type=int)
        command.add_argument("--max-reference-depth", type=int)
        command.add_argument("--json", action="store_true", dest="json_output")
        command.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
    evaluation = commands.add_parser("eval", help=COMMAND_HELP["eval"], description=COMMAND_HELP["eval"])
    evaluation_commands = evaluation.add_subparsers(dest="eval_command", title="eval commands", required=True)
    quality = evaluation_commands.add_parser("scenario-quality", help="assess package-local scenario definitions")
    quality.add_argument("package_root", type=Path)
    quality.add_argument("--source-revision")
    quality.add_argument("--scenario-set")
    quality.add_argument("--json", action="store_true", dest="json_output")
    quality.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
    tessl = commands.add_parser(
        "tessl",
        help="prepare or verify a Tessl candidate without publishing",
        description="prepare or verify a Tessl candidate without publishing",
    )
    tessl_commands = tessl.add_subparsers(dest="tessl_command", title="tessl commands")
    tessl_commands.add_parser(
        "prepare", help="prepare a candidate-bound Tessl payload", description="prepare a candidate-bound Tessl payload"
    )
    tessl_commands.add_parser(
        "verify", help="verify a prepared Tessl payload", description="verify a prepared Tessl payload"
    )
    return parser


def _human_findings(command: str, result: Any) -> tuple[Any, ...]:
    """Return findings suitable for the human-readable command output."""
    if command in {"validate", "scenario-quality"}:
        return tuple(result.findings)
    return (result.blocker,) if result.blocker is not None else ()


def _print_result(command: str, result: Any, *, json_output: bool) -> None:
    """Print a validation or build result in the requested output format."""
    if json_output:
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
        return
    package_id = result.candidate.package_id if result.candidate is not None else "unresolved-candidate"
    print(f"{command}: {result.status} ({package_id})")
    for finding in _human_findings(command, result):
        references = ", ".join(finding.evidence_refs)
        suffix = f" [{references}]" if references else ""
        print(f"  {finding.code}: {finding.message}{suffix}")


def _maintain_entrypoint(arguments: argparse.Namespace) -> int:
    """Run the bounded host-maintenance command and return its exit status."""
    from skills_sdk.host.entrypoint import (
        EntrypointMaintenanceBlocker,
        EntrypointMaintenanceResult,
        EntrypointRequest,
        check_entrypoint,
        repair_entrypoint,
    )

    try:
        request = EntrypointRequest(
            source=arguments.source,
            target=arguments.target,
            backup_root=arguments.backup_root,
            expected_source=arguments.expected_source,
            expected_current=arguments.expected_current,
            supporting_document=arguments.supporting_document,
        )
        result = repair_entrypoint(request) if arguments.apply else check_entrypoint(request)
    except (OSError, ValueError) as exc:
        result = EntrypointMaintenanceResult(
            status="blocked",
            blocker=EntrypointMaintenanceBlocker(code="entrypoint_maintenance_blocked", message=str(exc)),
        )
    if arguments.json_output:
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"maintain-entrypoint: {result.status}")
        if result.blocker is not None:
            print(f"  {result.blocker.code}: {result.blocker.message}")
        if result.backup_name is not None:
            print(f"  backup: {result.backup_name}")
        if result.recovery_name is not None:
            print(f"  recovery: {result.recovery_name}")
    return 0 if result.status in {"matching", "repaired"} else 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run implemented commands and preserve parse-only future boundaries."""
    arguments = build_parser().parse_args(argv)
    if arguments.command == "maintain-entrypoint":
        return _maintain_entrypoint(arguments)
    if arguments.command == "compare-copy":
        from skills_sdk.validation.runtime_copy import compare_runtime_copy

        comparison = compare_runtime_copy(arguments.source_root, arguments.runtime_root, arguments.source_revision)
        if arguments.json_output:
            print(json.dumps(comparison.model_dump(mode="json"), sort_keys=True))
            return 0 if comparison.status == "pass" else 2
        print(f"compare-copy: {comparison.status}")
        for label, validation in (("source", comparison.source), ("runtime", comparison.runtime)):
            for finding in validation.findings:
                print(f"  {label}: {finding.code}: {finding.message}")
        for path in comparison.different_paths:
            print(f"  different: {path}")
        return 0 if comparison.status == "pass" else 2
    if arguments.command == "eval" and arguments.eval_command == "scenario-quality":
        from skills_sdk.evaluation import assess_scenario_quality

        quality_result = assess_scenario_quality(
            arguments.package_root,
            source_revision=arguments.source_revision or "",
            scenario_set_id=arguments.scenario_set,
        )
        _print_result("scenario-quality", quality_result, json_output=arguments.json_output)
        return 0 if quality_result.status == "pass" else 2
    if arguments.command not in {"validate", "build"}:
        return 0
    from skills_sdk.validation import SkillValidationPolicy

    policy = SkillValidationPolicy(
        max_entrypoint_lines=arguments.max_entrypoint_lines,
        max_reference_depth=arguments.max_reference_depth,
    )
    if arguments.command == "validate":
        from skills_sdk.validation import validate_skill_package

        validation_result = validate_skill_package(
            arguments.package_root,
            source_revision=arguments.source_revision or "",
            policy=policy,
        )
        successful = validation_result.status == "pass"
        _print_result(arguments.command, validation_result, json_output=arguments.json_output)
    else:
        from skills_sdk.packaging import build_skill_package

        package_result = build_skill_package(
            arguments.package_root,
            source_revision=arguments.source_revision or "",
            policy=policy,
        )
        successful = package_result.status == "built"
        _print_result(arguments.command, package_result, json_output=arguments.json_output)
    return 0 if successful else 2


if __name__ == "__main__":
    raise SystemExit(main())
