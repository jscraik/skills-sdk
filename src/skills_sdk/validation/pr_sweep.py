"""Portable read-only checks for recurring PR findings and dirty closeout."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.pr_sweep import PrSweepDirtyState, PrSweepFinding, PrSweepValidationResult


def _failure(kind: str, status: str, code: str, message: str) -> PrSweepValidationResult:
    return PrSweepValidationResult.model_validate(
        {"kind": kind, "status": status, "findings": (PrSweepFinding(code=code, message=message),)}
    )


def validate_recurring_findings(ledger_path: Path) -> PrSweepValidationResult:
    """Validate one supplied ledger without changing it or executing a reviewer."""
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        return _failure("recurring_findings", "fail", "ledger_unreadable", "could not read or parse ledger JSON")
    schema = SchemaRegistry().load("pr-sweep-recurring-findings.v1")
    try:
        errors = [
            error.message for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(ledger)
        ]
    except RecursionError:
        return _failure("recurring_findings", "fail", "ledger_schema", "ledger structure exceeds validation depth")
    if errors or not isinstance(ledger, dict):
        return PrSweepValidationResult(
            kind="recurring_findings",
            status="fail",
            findings=tuple(PrSweepFinding(code="ledger_schema", message=message) for message in sorted(errors)),
        )

    seen_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    for finding in ledger["classes"]:
        class_id = finding["finding_class_id"]
        fingerprint = finding["fingerprint_sha256"]
        expected = hashlib.sha256(finding["normalized_invariant"].strip().lower().encode("utf-8")).hexdigest()
        if class_id in seen_ids:
            errors.append(f"duplicate finding_class_id: {class_id}")
        if fingerprint in seen_fingerprints:
            errors.append(f"duplicate fingerprint_sha256: {fingerprint}")
        if fingerprint != expected:
            errors.append(f"fingerprint_sha256 does not match normalized_invariant: {class_id}")
        seen_ids.add(class_id)
        seen_fingerprints.add(fingerprint)
        occurrences = finding["occurrences"]
        occurrence_keys = {(item["repository"], item["pull_request"], item["evidence_ref"]) for item in occurrences}
        if len(occurrence_keys) != len(occurrences):
            errors.append(f"duplicate occurrence evidence: {class_id}")
        expected_eligible = len(occurrences) < 3 or finding["guardrail"]["status"] == "validated"
        if finding["merge_eligible"] != expected_eligible:
            errors.append(f"merge_eligible must be {str(expected_eligible).lower()}: {class_id}")
    return PrSweepValidationResult(
        kind="recurring_findings",
        status="fail" if errors else "pass",
        findings=tuple(PrSweepFinding(code="ledger_invariant", message=message) for message in sorted(errors)),
    )


def _parse_porcelain(output: str) -> PrSweepDirtyState:
    staged: set[str] = set()
    unstaged: set[str] = set()
    untracked: set[str] = set()
    records = output.split("\x00")
    index = 0
    while index < len(records):
        line = records[index]
        index += 1
        if not line:
            continue
        status = line[:2]
        path = line[3:]
        paths = (path,)
        if ("R" in status or "C" in status) and index < len(records):
            paths = (path, records[index])
            index += 1
        if status == "??":
            untracked.update(paths)
            continue
        if status[0] != " ":
            staged.update(paths)
        if status[1] != " ":
            unstaged.update(paths)
    return PrSweepDirtyState(
        staged_paths=tuple(sorted(staged)),
        unstaged_paths=tuple(sorted(unstaged)),
        untracked_paths=tuple(sorted(untracked)),
        dirty_paths=tuple(sorted(staged | unstaged | untracked)),
    )


def _ledger_paths(value: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, str):
        if "/" in value or value.startswith("."):
            paths.add(value)
    elif isinstance(value, list):
        for item in value:
            paths.update(_ledger_paths(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"path", "file", "files", "paths", "changed_files", "dirty_paths", "ledgered_paths"}:
                paths.update(_recognized_paths(item))
            elif isinstance(item, (dict, list)):
                paths.update(_ledger_paths(item))
    return paths


def _recognized_paths(value: Any) -> set[str]:
    if isinstance(value, str) and value:
        return {value}
    if isinstance(value, list):
        paths: set[str] = set()
        for item in value:
            paths.update(_recognized_paths(item))
        return paths
    if isinstance(value, dict):
        return _ledger_paths(value)
    return set()


def validate_pr_sweep_dirty_closeout(
    repo_root: Path, *, ledger_path: Path | None = None, require_clean: bool = False
) -> PrSweepValidationResult:
    """Account for primary-checkout dirt; never equate a ledger with cleanliness."""
    try:
        top_level = subprocess.run(
            ["git", "--no-optional-locks", "rev-parse", "--show-toplevel"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if top_level.returncode != 0 or Path(top_level.stdout.strip()).resolve() != repo_root.resolve():
            return _failure(
                "dirty_closeout", "blocked", "invalid_repo_root", "supplied root is not a worktree top level"
            )
        completed = subprocess.run(
            ["git", "--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, UnicodeError, RuntimeError, subprocess.TimeoutExpired):
        return _failure("dirty_closeout", "blocked", "git_status_unavailable", "could not inspect Git dirty state")
    if completed.returncode != 0:
        return _failure(
            "dirty_closeout", "blocked", "git_status_unavailable", "Git status failed in the supplied repository root"
        )
    state = _parse_porcelain(completed.stdout)
    ledgered: set[str] = set()
    findings: list[PrSweepFinding] = []
    if ledger_path is not None:
        try:
            ledgered = _ledger_paths(json.loads(ledger_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
            findings.append(
                PrSweepFinding(code="ledger_unreadable", message="could not read or parse dirty-worktree ledger JSON")
            )
        safe_paths: set[str] = set()
        for path in ledgered:
            try:
                require_portable_relative_path(path)
            except ContractError:
                findings.append(
                    PrSweepFinding(code="invalid_ledger_path", message="dirty-worktree ledger contains an unsafe path")
                )
            else:
                safe_paths.add(path)
        ledgered = safe_paths
    unledgered = sorted(set(state.dirty_paths) - ledgered)
    if require_clean and state.dirty_paths:
        findings.append(
            PrSweepFinding(
                code="primary_worktree_dirty",
                message="primary checkout is dirty; branch movement requires a clean checkout",
            )
        )
    elif state.dirty_paths and ledger_path is None:
        findings.append(
            PrSweepFinding(
                code="dirty_worktree_ledger_required", message="dirty checkout requires a ledger for accounting"
            )
        )
    elif unledgered:
        findings.append(
            PrSweepFinding(code="dirty_worktree_unledgered_paths", message="dirty paths are missing from the ledger")
        )
    return PrSweepValidationResult(
        kind="dirty_closeout",
        status="fail" if findings else "pass",
        findings=tuple(findings),
        dirty_state=state,
        ledgered_paths=tuple(sorted(ledgered)),
        unledgered_paths=tuple(unledgered),
    )
