from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from skills_sdk import __version__

COMMAND_HELP = {
    "inventory": "inspect a read-only source inventory",
    "intake": "run read-only package intake and normalization",
    "validate": "run package contract validation",
    "build": "build an immutable package candidate",
    "eval": "run candidate-bound evaluation lanes",
    "package": "prepare a distributable package",
    "project": "project a candidate into a selected runtime surface",
    "verify": "verify candidate-bound evidence",
}
_MAX_INTAKE_CONTEXT_BYTES = 1_048_576


def _read_intake_context(path: Path) -> bytes:
    """Read one bounded, regular, no-follow intake context file."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_INTAKE_CONTEXT_BYTES:
            raise ValueError("invalid intake context file")
        chunks: list[bytes] = []
        captured = 0
        while captured <= _MAX_INTAKE_CONTEXT_BYTES:
            chunk = os.read(descriptor, min(65_536, _MAX_INTAKE_CONTEXT_BYTES + 1 - captured))
            if not chunk:
                break
            chunks.append(chunk)
            captured += len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(payload) > _MAX_INTAKE_CONTEXT_BYTES or (
            before.st_size,
            before.st_mtime_ns,
            before.st_ino,
        ) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("invalid intake context file")
        return payload
    finally:
        os.close(descriptor)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="skills-sdk",
        description="Portable lifecycle contracts and tooling for Agent Skills packages.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", title="commands")
    for name, help_text in COMMAND_HELP.items():
        if name in {"intake", "validate", "build"}:
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
    intake = commands.add_parser("intake", help=COMMAND_HELP["intake"], description=COMMAND_HELP["intake"])
    intake.add_argument("package_root", type=Path)
    intake.add_argument(
        "--context", type=Path, required=True, help="path to a skill-package-intake-context/v1 JSON file"
    )
    intake.add_argument("--max-entrypoint-lines", type=int)
    intake.add_argument("--max-reference-depth", type=int)
    intake.add_argument("--json", action="store_true", dest="json_output")
    intake.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
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
    package_id = result.candidate.package_id if result.candidate is not None else "unresolved-candidate"
    print(f"{command}: {result.status} ({package_id})")
    if command == "intake" and result.decision is not None:
        print(f"  decision: {result.decision.decision.value}")
        for code in result.decision.blocker_codes:
            print(f"  decision_blocker: {code}")
    for finding in _human_findings(command, result):
        references = ", ".join(finding.evidence_refs)
        suffix = f" [{references}]" if references else ""
        print(f"  {finding.code}: {finding.message}{suffix}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run implemented commands and preserve parse-only future boundaries."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command not in {"intake", "validate", "build"}:
        return 0
    from skills_sdk.validation import SkillValidationPolicy

    policy = SkillValidationPolicy(
        max_entrypoint_lines=arguments.max_entrypoint_lines,
        max_reference_depth=arguments.max_reference_depth,
    )
    if arguments.command == "intake":
        from pydantic import ValidationError

        from skills_sdk.core.errors import ContractError
        from skills_sdk.core.schema_registry import SchemaRegistry
        from skills_sdk.intake import intake_skill_package
        from skills_sdk.models.intake import SkillPackageIntakeContext

        try:
            context_payload = json.loads(_read_intake_context(arguments.context).decode("utf-8"))
            SchemaRegistry().validate("skill-package-intake-context.v1", context_payload)
            context = SkillPackageIntakeContext.model_validate(context_payload)
        except (ContractError, OSError, UnicodeDecodeError, ValueError, ValidationError):
            parser.error("invalid intake context")
        intake_result = intake_skill_package(arguments.package_root, context, policy=policy)
        successful = (
            intake_result.status == "normalized"
            and intake_result.decision is not None
            and intake_result.decision.decision.value == "admit"
        )
        _print_result(arguments.command, intake_result, json_output=arguments.json_output)
    elif arguments.command == "validate":
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
