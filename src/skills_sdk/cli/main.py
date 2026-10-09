from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

from skills_sdk import __version__
from skills_sdk.cli import COMMAND_HELP
from skills_sdk.cli.plugin import add_plugin_parser, run_plugin_validation
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput

_MAX_INTAKE_CONTEXT_BYTES = 1_048_576


class _UnsupportedContextRead(OSError):
    """Safe context traversal is unavailable on this host."""


class _ContextReadLimitExceeded(ValueError):
    """The supplied regular file exceeds this command's read budget."""


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
        or not {os.open, os.stat}.issubset(os.supports_dir_fd)
        or os.stat not in os.supports_follow_symlinks
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
        leaf = os.stat(absolute.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(leaf.st_mode):
            raise ValueError("invalid intake context file")
        return os.open(absolute.name, os.O_RDONLY | nonblock | nofollow, dir_fd=parent)
    finally:
        os.close(parent)


def _read_intake_context(path: Path, *, max_bytes: int = _MAX_INTAKE_CONTEXT_BYTES) -> bytes:
    """Read one bounded, regular, no-follow intake context file."""
    descriptor = _open_intake_context(path)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("invalid intake context file")
        if before.st_size > max_bytes:
            raise _ContextReadLimitExceeded("context file exceeds the command read budget")
        chunks: list[bytes] = []
        captured = 0
        while captured <= max_bytes:
            chunk = os.read(descriptor, min(65_536, max_bytes + 1 - captured))
            if not chunk:
                break
            chunks.append(chunk)
            captured += len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(payload) > max_bytes:
            raise _ContextReadLimitExceeded("context file exceeds the command read budget")
        if (
            before.st_size,
            before.st_mtime_ns,
            before.st_ino,
        ) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("invalid intake context file")
        return payload
    finally:
        os.close(descriptor)


def _add_coverage_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    coverage = commands.add_parser("scenario-coverage", help="audit declared claims against active cases and gaps")
    coverage.add_argument("package_root", type=Path)
    coverage.add_argument("--source-revision", required=True)
    coverage.add_argument("--scenario-set", required=True)
    coverage.add_argument("--coverage-plan", type=Path, required=True)
    coverage.add_argument("--json", action="store_true", dest="json_output")
    coverage.add_argument("--robot", action="store_true")


def _add_content_review_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    review = commands.add_parser("review-content", help="bind supplied content review to the current package")
    review.add_argument("package_root", type=Path)
    review.add_argument("--source-revision", required=True)
    review.add_argument("--assessment", type=Path, required=True)
    review.add_argument("--json", action="store_true", dest="json_output")
    review.add_argument("--robot", action="store_true")


def _add_quality_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the v2 quality command and its request, baseline, and assessment inputs."""
    quality = commands.add_parser("check-quality", help="run explicit v2 intent, policy and content quality checks")
    quality.add_argument("package_root", type=Path)
    quality.add_argument("--request", type=Path, required=True)
    quality.add_argument("--baseline-root", type=Path)
    quality.add_argument("--assessment", type=Path)
    quality.add_argument("--json", action="store_true", dest="json_output")
    quality.add_argument("--robot", action="store_true")


def _add_scorer_parsers(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register read-only assessments and the explicitly offline execution route."""
    from skills_sdk.cli.observed_calibration import add_parser as add_calibration_parser

    add_calibration_parser(commands)
    for name, help_text in (
        ("scorer-quality", "assess candidate scorer declarations without executing a judge"),
        ("scorer-calibration", "assess candidate-bound held-out scorer artifacts"),
    ):
        scorer = commands.add_parser(name, help=help_text)
        scorer.add_argument("package_root", type=Path)
        scorer.add_argument("--source-revision", required=True)
        scorer.add_argument("--json", action="store_true", dest="json_output")
        scorer.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="skills-sdk",
        description="Portable lifecycle contracts and tooling for Agent Skills packages.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", title="commands")
    _add_content_review_parser(commands)
    _add_quality_parser(commands)
    add_plugin_parser(commands)
    for name, help_text in COMMAND_HELP.items():
        if name in {"intake", "check-local", "validate", "build", "eval", "verify"}:
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
        command.add_argument(
            "--require-file", action="append", default=[], help="require an applicable package-local file"
        )
        command.add_argument(
            "--check-reference-content", action="store_true", help="check textual reference bytes and syntax"
        )
        command.add_argument("--json", action="store_true", dest="json_output")
        command.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
    intake = commands.add_parser("intake", help=COMMAND_HELP["intake"], description=COMMAND_HELP["intake"])
    intake.add_argument("package_root", type=Path)
    intake.add_argument(
        "--context", type=Path, required=True, help="path to a skill-package-intake-context/v1 JSON file"
    )
    intake.add_argument("--max-entrypoint-lines", type=int)
    intake.add_argument("--max-reference-depth", type=int)
    intake.add_argument("--require-file", action="append", default=[], help="require an applicable package-local file")
    intake.add_argument(
        "--check-reference-content", action="store_true", help="check textual reference bytes and syntax"
    )
    intake.add_argument("--json", action="store_true", dest="json_output")
    intake.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
    local_check = commands.add_parser("check-local", help=COMMAND_HELP["check-local"])
    local_check.add_argument("package_root", type=Path)
    local_check.add_argument("--context", type=Path, required=True)
    local_check.add_argument("--scenario-set", required=True)
    local_check.add_argument("--json", action="store_true", dest="json_output")
    local_check.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
    evaluation = commands.add_parser("eval", help=COMMAND_HELP["eval"], description=COMMAND_HELP["eval"])
    evaluation_commands = evaluation.add_subparsers(dest="eval_command", title="eval commands", required=True)
    quality = evaluation_commands.add_parser("scenario-quality", help="assess package-local scenario definitions")
    quality.add_argument("package_root", type=Path)
    quality.add_argument("--source-revision")
    quality.add_argument("--scenario-set")
    quality.add_argument("--contract-version", choices=("v1", "v2"), default="v1")
    quality.add_argument("--json", action="store_true", dest="json_output")
    quality.add_argument("--robot", action="store_true", help="reserve the prompt-free automation contract")
    _add_coverage_parser(evaluation_commands)
    _add_scorer_parsers(evaluation_commands)
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
    verify = commands.add_parser("verify", help=COMMAND_HELP["verify"], description=COMMAND_HELP["verify"])
    verify_commands = verify.add_subparsers(dest="verify_command", title="verify commands", required=True)
    recurring = verify_commands.add_parser("recurring-findings", help="validate a PR-sweep recurring-finding ledger")
    recurring.add_argument("ledger", type=Path)
    recurring.add_argument("--json", action="store_true", dest="json_output")
    recurring.add_argument("--robot", action="store_true")
    closeout = verify_commands.add_parser("pr-sweep-dirty-closeout", help="validate primary-checkout dirty state")
    closeout.add_argument("--repo-root", type=Path, required=True)
    closeout.add_argument("--ledger", type=Path)
    closeout.add_argument("--require-clean", action="store_true")
    closeout.add_argument("--json", action="store_true", dest="json_output")
    closeout.add_argument("--robot", action="store_true")
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
    if command in {
        "validate",
        "review-content",
        "scenario-quality",
        "scenario-coverage",
        "scorer-quality",
        "scorer-calibration",
    }:
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
    if command == "selected-case":
        for case in result.case_results:
            print(f"  case {case.case_id}: {case.status}")
            if case.missing_signals:
                print(f"    missing_signals: {', '.join(case.missing_signals)}")
            if case.forbidden_commands_observed:
                print(f"    forbidden_commands_observed: {', '.join(case.forbidden_commands_observed)}")
            if case.blocker is not None:
                print(f"    {case.blocker.code}: {case.blocker.message}")


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

    blocker = PackageReceiptBlocker(code=code, message=message)
    if json_output:
        print(json.dumps(blocker.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"selected-case: blocked\n  {blocker.code}: {blocker.message}")
    return 2


def _content_review(arguments: argparse.Namespace) -> int:
    from skills_sdk.models.content_review import CONTENT_REVIEW_ASSESSMENT_MAX_BYTES
    from skills_sdk.validation import assess_content_review

    try:
        assessment = json.loads(
            _read_intake_context(arguments.assessment, max_bytes=CONTENT_REVIEW_ASSESSMENT_MAX_BYTES).decode("utf-8"),
            object_pairs_hook=_reject_duplicate_members,
        )
    except (_UnsupportedContextRead, _ContextReadLimitExceeded) as error:
        from skills_sdk.models.packaging import PackageReceiptBlocker

        blocker = PackageReceiptBlocker(
            code="unsupported_context_read"
            if isinstance(error, _UnsupportedContextRead)
            else "content_review_input_limit",
            message="safe descriptor-relative assessment reads are unavailable"
            if isinstance(error, _UnsupportedContextRead)
            else "assessment JSON exceeds the eight MiB read budget",
            evidence_refs=("docs/compatibility.md",),
        )
        if arguments.json_output:
            print(json.dumps(blocker.model_dump(mode="json"), sort_keys=True))
        else:
            print(f"review-content: blocked\n  {blocker.code}: {blocker.message}")
        return 2
    except (OSError, ValueError, RecursionError):
        assessment = None
    result = assess_content_review(
        arguments.package_root, source_revision=arguments.source_revision, assessment=assessment
    )
    _print_result("review-content", result, json_output=arguments.json_output)
    return 0 if result.status == "pass" else 2


def _scenario_coverage(arguments: argparse.Namespace) -> int:
    from skills_sdk.evaluation import assess_scenario_coverage

    try:
        plan = json.loads(
            _read_intake_context(arguments.coverage_plan).decode("utf-8"),
            object_pairs_hook=_reject_duplicate_members,
        )
    except (OSError, ValueError, RecursionError):
        plan = None
    result = assess_scenario_coverage(
        arguments.package_root,
        source_revision=arguments.source_revision,
        scenario_set_id=arguments.scenario_set,
        coverage_plan=plan,
    )
    _print_result("scenario-coverage", result, json_output=arguments.json_output)
    return 0 if result.status == "pass" else 2


def _selected_case_host_input(path: Path) -> tuple[object, object, object | None, object | None, object | None]:
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
        "safety_evidence",
    }:
        raise ValueError("invalid selected-case host input")
    return (
        payload.get("request"),
        payload.get("input_payload"),
        payload.get("adapter"),
        payload.get("assertion_evidence"),
        payload.get("safety_evidence"),
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
        request_payload, input_payload, adapter_payload, evidence_payload, safety_payload = _selected_case_host_input(
            arguments.host_input
        )
        request = ProviderExecutionRequest.model_validate(request_payload)
        adapter = cast(TextProviderAdapter | None, _supplied_adapter(adapter_payload))
        evidence = None if evidence_payload is None else SelectedCaseJudgeEvidence.model_validate(evidence_payload)
        receipt = asyncio.run(
            execute_selected_case(
                definition,
                request,
                SelectedCaseExecutionInput(cast(JsonValue, input_payload), safety_payload),
                adapter,
                evidence,
            )
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


def _verify(arguments: argparse.Namespace) -> int:
    """Run a selected verification and render its result."""
    from skills_sdk.validation import validate_pr_sweep_dirty_closeout, validate_recurring_findings

    if arguments.verify_command == "recurring-findings":
        verification = validate_recurring_findings(arguments.ledger)
    else:
        verification = validate_pr_sweep_dirty_closeout(
            arguments.repo_root, ledger_path=arguments.ledger, require_clean=arguments.require_clean
        )
    if arguments.json_output:
        print(json.dumps(verification.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"verify {arguments.verify_command}: {verification.status}")
        for finding in verification.findings:
            print(f"  {finding.code}: {finding.message}")
    return 0 if verification.status == "pass" else 2


def _emit_local_check(
    stages: list[tuple[str, Any]], *, blocked_stage: str | None, json_output: bool, blocker: Any = None
) -> int:
    """Expose existing typed receipts without promoting a local check to admission."""
    from skills_sdk.models.local_check import LocalCheckResult, LocalCheckStage

    result = LocalCheckResult(
        status="blocked" if blocked_stage else "local_checks_passed",
        candidate=stages[0][1].candidate if stages else None,
        blocked_stage=blocked_stage,
        stages=tuple(LocalCheckStage(name=name, receipt=receipt) for name, receipt in stages),
        blocker=blocker,
    )
    if json_output:
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"local-check: {result.status}")
        for name, receipt in stages:
            print(f"  {name}: {receipt.status}")
        if blocked_stage:
            print(f"  blocked_stage: {blocked_stage}")
        if stages and blocked_stage and blocked_stage != "candidate_changed":
            final_receipt = stages[-1][1]
            decision = getattr(final_receipt, "decision", None)
            if decision is not None:
                print(f"  decision: {decision.decision.value}")
                for code in decision.blocker_codes:
                    print(f"  decision_blocker: {code}")
            for finding in getattr(final_receipt, "findings", ()):
                print(f"  {finding.code}: {finding.message}")
            final_blocker = getattr(final_receipt, "blocker", None)
            if final_blocker is not None:
                print(f"  {final_blocker.code}: {final_blocker.message}")
        if blocker is not None:
            print(f"  {blocker.code}: {blocker.message}")
    return 2 if blocked_stage else 0


def _local_check(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Compose read-only, candidate-bound local checks in fail-closed order."""
    from pydantic import ValidationError

    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.evaluation import assess_scenario_quality, assess_scorer_calibration, assess_scorer_quality
    from skills_sdk.intake import intake_skill_package
    from skills_sdk.models.intake import SkillPackageIntakeContext
    from skills_sdk.validation import validate_skill_package

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
        return _emit_local_check([], blocked_stage="context", json_output=arguments.json_output, blocker=blocker)
    except (ContractError, OSError, RecursionError, UnicodeDecodeError, ValueError, ValidationError):
        parser.error("invalid intake context")
    root = arguments.package_root
    revision = context.source_revision
    intake = intake_skill_package(root, context)
    stages: list[tuple[str, Any]] = [("intake", intake)]
    if intake.status != "normalized" or intake.decision is None or intake.decision.decision.value != "admit":
        return _emit_local_check(stages, blocked_stage="intake", json_output=arguments.json_output)
    checks: tuple[tuple[str, Callable[[], Any]], ...] = (
        ("validate", lambda: validate_skill_package(root, source_revision=revision)),
        (
            "scenario-quality",
            lambda: assess_scenario_quality(
                root, source_revision=revision, scenario_set_id=arguments.scenario_set, contract_version="v2"
            ),
        ),
        ("scorer-quality", lambda: assess_scorer_quality(root, source_revision=revision)),
        ("scorer-calibration", lambda: assess_scorer_calibration(root, source_revision=revision)),
    )
    for name, check in checks:
        receipt = check()
        stages.append((name, receipt))
        if receipt.candidate != intake.candidate:
            return _emit_local_check(stages, blocked_stage="candidate_changed", json_output=arguments.json_output)
        if receipt.status != "pass":
            return _emit_local_check(stages, blocked_stage=name, json_output=arguments.json_output)
    return _emit_local_check(stages, blocked_stage=None, json_output=arguments.json_output)


def _quality_check(arguments: argparse.Namespace) -> int:
    """Read bounded no-follow inputs and return the v2 envelope even on rejection."""
    from skills_sdk.evaluation import check_local_quality
    from skills_sdk.models.content_review import CONTENT_REVIEW_ASSESSMENT_MAX_BYTES
    from skills_sdk.models.packaging import PackageReceiptBlocker
    from skills_sdk.models.quality_workflow import LocalCheckResultV2

    try:
        request = json.loads(
            _read_intake_context(arguments.request).decode("utf-8"), object_pairs_hook=_reject_duplicate_members
        )
        assessment = None
        if arguments.assessment is not None:
            assessment = json.loads(
                _read_intake_context(arguments.assessment, max_bytes=CONTENT_REVIEW_ASSESSMENT_MAX_BYTES).decode(
                    "utf-8"
                ),
                object_pairs_hook=_reject_duplicate_members,
            )
    except (OSError, ValueError, RecursionError):
        result = LocalCheckResultV2(
            status="blocked",
            request=None,
            blocked_stage="request",
            blocker=PackageReceiptBlocker(
                code="invalid_quality_input", message="Quality inputs require bounded no-follow JSON files."
            ),
        )
    else:
        result = asyncio.run(
            check_local_quality(
                arguments.package_root,
                request,
                baseline_root=arguments.baseline_root,
                assessment=assessment,
            )
        )
    if arguments.json_output:
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"check-quality: {result.status}")
        if result.blocker is not None:
            print(f"  {result.blocked_stage}: {result.blocker.code}: {result.blocker.message}")
        if (
            result.stages
            and result.blocked_stage not in {None, "candidate_changed", "final-capture"}
            and result.stages[-1].name == result.blocked_stage
        ):
            receipt = result.stages[-1].receipt
            decision = getattr(receipt, "decision", None)
            if decision is not None:
                print(f"  decision: {decision.decision.value}")
                for code in decision.blocker_codes:
                    print(f"  decision_blocker: {code}")
            validation = getattr(receipt, "validation", None)
            findings = getattr(receipt, "findings", None) or getattr(validation, "findings", ())
            for finding in findings:
                print(f"  {finding.code}: {finding.message}")
            receipt_blocker = getattr(receipt, "blocker", None)
            if receipt_blocker is not None:
                print(f"  {receipt_blocker.code}: {receipt_blocker.message}")
    return 0 if result.status == "local_checks_passed" else 2


def _evaluation_command(arguments: argparse.Namespace) -> int:
    """Dispatch evaluation lanes without changing their distinct evidence claims."""
    if arguments.eval_command == "scenario-coverage":
        return _scenario_coverage(arguments)
    if arguments.eval_command == "scenario-quality":
        from skills_sdk.evaluation import assess_scenario_quality

        quality_result = assess_scenario_quality(
            arguments.package_root,
            source_revision=arguments.source_revision or "",
            scenario_set_id=arguments.scenario_set,
            contract_version=arguments.contract_version,
        )
        _print_result("scenario-quality", quality_result, json_output=arguments.json_output)
        return 0 if quality_result.status == "pass" else 2
    if arguments.eval_command == "selected-case":
        return _selected_case_eval(arguments)
    if arguments.eval_command == "observed-calibration":
        from skills_sdk.cli.observed_calibration import run as run_calibration

        return run_calibration(arguments, _read_intake_context, _reject_duplicate_members)
    from skills_sdk.evaluation import assess_scorer_calibration, assess_scorer_quality

    assessor = assess_scorer_quality if arguments.eval_command == "scorer-quality" else assess_scorer_calibration
    receipt = assessor(arguments.package_root, source_revision=arguments.source_revision)
    _print_result(arguments.eval_command, receipt, json_output=arguments.json_output)
    return 0 if receipt.status == "pass" else 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run implemented commands and preserve parse-only future boundaries."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "check-quality":
        return _quality_check(arguments)
    if arguments.command == "review-content":
        return _content_review(arguments)
    if arguments.command == "check-local":
        return _local_check(arguments, parser)
    if arguments.command == "verify":
        return _verify(arguments)
    if arguments.command == "validate-plugin":
        return run_plugin_validation(
            arguments,
            lambda path: _read_intake_context(path, max_bytes=16 * 1024 * 1024),
            _reject_duplicate_members,
        )
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
    if arguments.command == "eval":
        return _evaluation_command(arguments)
    if arguments.command not in {"intake", "validate", "build"}:
        return 0
    from skills_sdk.validation import SkillValidationPolicy

    policy = SkillValidationPolicy(
        max_entrypoint_lines=arguments.max_entrypoint_lines,
        max_reference_depth=arguments.max_reference_depth,
        required_files=tuple(arguments.require_file),
        check_reference_content=arguments.check_reference_content,
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
