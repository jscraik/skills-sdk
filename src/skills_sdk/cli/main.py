from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

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


class _UnsupportedContextRead(OSError):
    """Safe context traversal is unavailable on this host."""


def _reject_duplicate_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while rejecting duplicate member names."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate intake context member")
        result[key] = value
    return result


def _open_intake_context(path: Path) -> int:
    """Open a context file without following any path component."""
    directory = getattr(os, "O_DIRECTORY", None)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if (
        any(not isinstance(flag, int) or flag == 0 for flag in (directory, nofollow, nonblock))
        or os.open not in os.supports_dir_fd
    ):
        raise _UnsupportedContextRead("safe descriptor-relative context reads are unavailable")
    if ".." in path.parts:
        raise ValueError("parent traversal is not allowed in an intake context path")
    absolute = path.absolute()
    parent = os.open(absolute.anchor, os.O_RDONLY | directory | nofollow)
    try:
        for component in absolute.parent.parts[1:]:
            child = os.open(component, os.O_RDONLY | directory | nofollow, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(absolute.name, os.O_RDONLY | nonblock | nofollow, dir_fd=parent)
    finally:
        os.close(parent)


def _read_intake_context(path: Path) -> bytes:
    """Read one bounded, regular, no-follow intake context file."""
    descriptor = _open_intake_context(path)
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
        if name in {"intake", "validate", "build", "eval"}:
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
    intake = commands.add_parser("intake", help=COMMAND_HELP["intake"], description=COMMAND_HELP["intake"])
    intake.add_argument("package_root", type=Path)
    intake.add_argument(
        "--context", type=Path, required=True, help="path to a skill-package-intake-context/v1 JSON file"
    )
    intake.add_argument("--max-entrypoint-lines", type=int)
    intake.add_argument("--max-reference-depth", type=int)
    intake.add_argument("--json", action="store_true", dest="json_output")
    intake.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
    evaluation = commands.add_parser("eval", help=COMMAND_HELP["eval"], description=COMMAND_HELP["eval"])
    evaluation_commands = evaluation.add_subparsers(dest="eval_command", title="eval commands", required=True)
    quality = evaluation_commands.add_parser("scenario-quality", help="assess package-local scenario definitions")
    quality.add_argument("package_root", type=Path)
    quality.add_argument("--source-revision")
    quality.add_argument("--scenario-set")
    quality.add_argument("--json", action="store_true", dest="json_output")
    quality.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
    selected = evaluation_commands.add_parser(
        "selected-case",
        help="evaluate one package-local case through caller-supplied provider evidence",
    )
    selected.add_argument("package_root", type=Path)
    selected.add_argument("--source-revision", required=True)
    selected.add_argument("--case", required=True, dest="case_id")
    selected.add_argument("--mode", choices=("smoke", "release"), required=True)
    selected.add_argument("--host-input", type=Path, required=True)
    selected.add_argument("--json", action="store_true", dest="json_output")
    selected.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
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
    if command == "intake" and result.decision is not None:
        print(f"  decision: {result.decision.decision.value}")
        for code in result.decision.blocker_codes:
            print(f"  decision_blocker: {code}")
    for finding in _human_findings(command, result):
        references = ", ".join(finding.evidence_refs)
        suffix = f" [{references}]" if references else ""
        print(f"  {finding.code}: {finding.message}{suffix}")


def _maintain_entrypoint(arguments: argparse.Namespace) -> int:
    """Run the bounded host-maintenance command and return its exit status."""
    from skills_sdk.models.maintenance import EntrypointMaintenanceBlocker, EntrypointMaintenanceResult

    try:
        from skills_sdk.host.entrypoint import EntrypointRequest, check_entrypoint, repair_entrypoint

        request = EntrypointRequest(
            source=arguments.source,
            target=arguments.target,
            backup_root=arguments.backup_root,
            expected_source=arguments.expected_source,
            expected_current=arguments.expected_current,
            supporting_document=arguments.supporting_document,
        )
        result = repair_entrypoint(request) if arguments.apply else check_entrypoint(request)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
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


def _selected_case_blocker(code: str, message: str, *, json_output: bool) -> int:
    """Print a selected-case blocker and return the blocked exit status."""
    from skills_sdk.models.packaging import PackageReceiptBlocker

    blocker = PackageReceiptBlocker(code=code, message=message, evidence_refs=("references/evals.yaml",))
    if json_output:
        print(json.dumps(blocker.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"selected-case: blocked\n  {blocker.code}: {blocker.message}")
    return 2


def _selected_case_host_input(path: Path) -> tuple[object, object, object | None, object | None]:
    """Load the bounded host-supplied inputs for one selected-case run."""
    payload = json.loads(
        _read_intake_context(path).decode("utf-8"),
        object_pairs_hook=_reject_duplicate_members,
    )
    if not isinstance(payload, dict) or set(payload) - {
        "adapter",
        "assertion_evidence",
        "input_payload",
        "request",
    }:
        raise ValueError("invalid selected-case host input")
    return (
        payload.get("request"),
        payload.get("input_payload"),
        payload.get("adapter"),
        payload.get("assertion_evidence"),
    )


def _supplied_adapter(payload: object) -> object | None:
    """Validate and construct the caller-supplied text adapter, if present."""
    if payload is None:
        return None
    if not isinstance(payload, dict) or set(payload) != {"descriptor", "evidence_refs", "output_text"}:
        raise ValueError("invalid supplied adapter")
    from skills_sdk.evaluation import SuppliedTextProviderAdapter
    from skills_sdk.models.provider_call import TextProviderAdapterDescriptor

    output_text = payload["output_text"]
    evidence_refs = payload["evidence_refs"]
    if not isinstance(output_text, str) or not isinstance(evidence_refs, list):
        raise ValueError("invalid supplied adapter")
    return SuppliedTextProviderAdapter(
        descriptor=TextProviderAdapterDescriptor.model_validate(payload["descriptor"]),
        text=output_text,
        evidence_refs=tuple(evidence_refs),
    )


def _selected_case_eval(arguments: argparse.Namespace) -> int:
    """Execute the selected-case CLI route and report its receipt."""
    from pydantic import ValidationError

    from skills_sdk.core.errors import ContractError
    from skills_sdk.evaluation import execute_selected_case, load_selected_case
    from skills_sdk.models.provider_execution import ProviderExecutionRequest
    from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence
    from skills_sdk.providers import JsonValue, TextProviderAdapter

    try:
        definition = load_selected_case(
            arguments.package_root,
            source_revision=arguments.source_revision,
            case_id=arguments.case_id,
            mode=arguments.mode,
        )
        request_payload, input_payload, adapter_payload, evidence_payload = _selected_case_host_input(
            arguments.host_input
        )
        request = ProviderExecutionRequest.model_validate(request_payload)
        adapter = cast(TextProviderAdapter | None, _supplied_adapter(adapter_payload))
        evidence = None if evidence_payload is None else SelectedCaseJudgeEvidence.model_validate(evidence_payload)
        receipt = asyncio.run(
            execute_selected_case(definition, request, cast(JsonValue, input_payload), adapter, evidence)
        )
    except ContractError as exc:
        return _selected_case_blocker(exc.code, exc.message, json_output=arguments.json_output)
    except (OSError, RecursionError, UnicodeDecodeError, ValueError, ValidationError):
        return _selected_case_blocker(
            "invalid_selected_case_input",
            "selected-case host input failed validation",
            json_output=arguments.json_output,
        )
    _print_result("selected-case", receipt, json_output=arguments.json_output)
    return 0 if receipt.status == "pass" else 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run implemented commands and preserve parse-only future boundaries."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
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
    if arguments.command == "eval" and arguments.eval_command == "selected-case":
        return _selected_case_eval(arguments)
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
            context_payload = json.loads(
                _read_intake_context(arguments.context).decode("utf-8"),
                object_pairs_hook=_reject_duplicate_members,
            )
            SchemaRegistry().validate("skill-package-intake-context.v1", context_payload)
            context = SkillPackageIntakeContext.model_validate(context_payload)
        except _UnsupportedContextRead:
            from skills_sdk.models.packaging import PackageReceiptBlocker

            blocker = PackageReceiptBlocker(
                code="unsupported_context_read",
                message="safe descriptor-relative intake context reads are unavailable",
                evidence_refs=("docs/compatibility.md",),
            )
            if arguments.json_output:
                print(json.dumps(blocker.model_dump(mode="json"), sort_keys=True))
            else:
                print(f"intake: blocked\n  {blocker.code}: {blocker.message}")
            return 2
        except (ContractError, OSError, RecursionError, UnicodeDecodeError, ValueError, ValidationError):
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
