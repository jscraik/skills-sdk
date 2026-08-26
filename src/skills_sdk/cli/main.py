from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from skills_sdk import __version__

COMMAND_HELP = {
    "inventory": "inspect a read-only source inventory",
    "intake": "validate a copy-first package intake decision",
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
        if name in {"validate", "build"}:
            continue
        commands.add_parser(name, help=help_text, description=help_text)
    for name in ("validate", "build"):
        command = commands.add_parser(name, help=COMMAND_HELP[name], description=COMMAND_HELP[name])
        command.add_argument("package_root", type=Path)
        command.add_argument("--source-revision")
        command.add_argument("--max-entrypoint-lines", type=int)
        command.add_argument("--max-reference-depth", type=int)
        command.add_argument("--json", action="store_true", dest="json_output")
        command.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
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
    if command == "validate":
        return tuple(result.findings)
    return (result.blocker,) if result.blocker is not None else ()


def _print_result(command: str, result: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
        return
    print(f"{command}: {result.status} ({result.candidate.package_id})")
    for finding in _human_findings(command, result):
        references = ", ".join(finding.evidence_refs)
        suffix = f" [{references}]" if references else ""
        print(f"  {finding.code}: {finding.message}{suffix}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run implemented commands and preserve parse-only future boundaries."""
    arguments = build_parser().parse_args(argv)
    if arguments.command not in {"validate", "build"}:
        return 0
    from skills_sdk.validation import SkillValidationPolicy

    policy = SkillValidationPolicy(
        max_entrypoint_lines=arguments.max_entrypoint_lines,
        max_reference_depth=arguments.max_reference_depth,
    )
    if arguments.command == "validate":
        from skills_sdk.validation import validate_skill_package

        result = validate_skill_package(
            arguments.package_root,
            source_revision=arguments.source_revision or "",
            policy=policy,
        )
        successful = result.status == "pass"
    else:
        from skills_sdk.packaging import build_skill_package

        result = build_skill_package(
            arguments.package_root,
            source_revision=arguments.source_revision or "",
            policy=policy,
        )
        successful = result.status == "built"
    _print_result(arguments.command, result, json_output=arguments.json_output)
    return 0 if successful else 2


if __name__ == "__main__":
    raise SystemExit(main())
