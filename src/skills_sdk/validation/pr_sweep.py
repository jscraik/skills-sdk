"""Portable read-only checks for recurring PR findings and dirty closeout."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.pr_sweep import PrSweepDirtyState, PrSweepFinding, PrSweepValidationResult


def _failure(kind: str, status: str, code: str, message: str) -> PrSweepValidationResult:
    return PrSweepValidationResult.model_validate(
        {"kind": kind, "status": status, "findings": (PrSweepFinding(code=code, message=message),)}
    )


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _read_ledger(path: Path) -> Any:
    """Read bounded regular JSON input without following a final symlink."""
    flags = os.O_RDONLY | os.O_NONBLOCK
    if not hasattr(os, "O_NOFOLLOW"):
        raise OSError("no-follow file opening is unavailable")
    descriptor = os.open(path, flags | os.O_NOFOLLOW)
    try:
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("ledger is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("ledger exceeds size limit")
        return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_members, parse_constant=_reject_constant)
    finally:
        os.close(descriptor)


def _occurrence_reference_matches(item: dict[str, Any]) -> bool:
    reference = item["evidence_ref"]
    if reference.startswith("https://github.com/"):
        parsed = urlsplit(reference)
        parts = parsed.path.strip("/").split("/")
        if parsed.netloc != "github.com" or parsed.query or parsed.fragment or len(parts) < 4:
            return False
        if f"{parts[0]}/{parts[1]}" != item["repository"]:
            return False
        if parts[2] == "pull":
            return len(parts) == 4 and parts[3] == str(item["pull_request"])
        return len(parts) == 5 and parts[2:4] == ["actions", "runs"]
    return True


def _local_evidence_reference_is_safe(reference: str) -> bool:
    match = re.fullmatch(r"(.+):([0-9]+)", reference)
    if match is None:
        return True
    try:
        require_portable_relative_path(match.group(1))
    except ContractError:
        return False
    return True


def validate_recurring_findings(ledger_path: Path) -> PrSweepValidationResult:
    """Validate one supplied ledger without changing it or executing a reviewer."""
    try:
        ledger = _read_ledger(ledger_path)
    except (OSError, UnicodeError, ValueError, RecursionError):
        return _failure("recurring_findings", "fail", "ledger_unreadable", "could not read or parse ledger JSON")
    schema = SchemaRegistry().load("pr-sweep-recurring-findings.v1")
    try:
        errors = [
            f"ledger schema constraint failed: {error.validator}"
            for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(ledger)
        ]
    except RecursionError:
        return _failure("recurring_findings", "fail", "ledger_schema", "ledger structure exceeds validation depth")
    if errors or not isinstance(ledger, dict):
        return PrSweepValidationResult(
            kind="recurring_findings",
            status="fail",
            findings=tuple(PrSweepFinding(code="ledger_schema", message=message) for message in sorted(errors)),
        )

    for finding in ledger["classes"]:
        references = [item["evidence_ref"] for item in finding["occurrences"]]
        guardrail = finding["guardrail"]
        references.append(guardrail.get("artifact_ref", guardrail.get("blocker_ref", "")))
        if any(not _local_evidence_reference_is_safe(ref) for ref in references):
            errors.append("ledger contains an unsafe local evidence reference")

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
        if any(not _occurrence_reference_matches(item) for item in occurrences):
            errors.append(f"occurrence evidence does not match repository and pull request: {class_id}")
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
            unstaged.add(path)
    return PrSweepDirtyState(
        staged_paths=tuple(sorted(staged)),
        unstaged_paths=tuple(sorted(unstaged)),
        untracked_paths=tuple(sorted(untracked)),
        dirty_paths=tuple(sorted(staged | unstaged | untracked)),
    )


def _ledger_paths(value: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, list):
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


def _git_environment() -> dict[str, str]:
    discovery_keys = {"GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM"}
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_") or key in discovery_keys}


def _run_git(repo_root: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "--no-optional-locks", *args],
        cwd=repo_root,
        env=_git_environment(),
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _git_status_preflight(repo_root: Path, *, depth: int = 0) -> tuple[str | None, str | None]:
    """Reject index or attributes that can hide dirt or execute a clean filter."""
    if depth > 8:
        return "git_status_unavailable", "submodule nesting exceeds safe inspection depth"
    tracked = _run_git(repo_root, "ls-files", "-v", "-z")
    if tracked.returncode != 0:
        return "git_status_unavailable", "could not inspect tracked Git paths"
    records = [record for record in tracked.stdout.split("\0") if record]
    if any(len(record) < 3 or record[1] != " " for record in records):
        return "git_status_unavailable", "could not parse tracked Git paths"
    if any(record[0].islower() or record[0] == "S" for record in records):
        return "index_visibility_flags", "index visibility flags prevent a trustworthy clean result"
    staged = _run_git(repo_root, "ls-files", "--stage", "-z")
    if staged.returncode != 0:
        return "git_status_unavailable", "could not inspect tracked Git modes"
    for record in staged.stdout.split("\0"):
        if not record.startswith("160000 "):
            continue
        _, separator, path = record.partition("\t")
        if not separator:
            return "git_status_unavailable", "could not parse tracked Git modes"
        submodule_root = repo_root / path
        if submodule_root.is_symlink():
            return "git_status_unavailable", "submodule path is not safe to inspect"
        if (submodule_root / ".git").exists():
            blocker_code, blocker_message = _git_status_preflight(submodule_root, depth=depth + 1)
            if blocker_code is not None:
                return blocker_code, blocker_message
    paths = [record[2:] for record in records]
    if paths:
        attributes = _run_git(repo_root, "check-attr", "-z", "--stdin", "filter", input_text="\0".join(paths) + "\0")
        if attributes.returncode != 0:
            return "git_status_unavailable", "could not inspect tracked Git attributes"
        fields = attributes.stdout.split("\0")
        if fields[-1] != "" or (len(fields) - 1) % 3 != 0:
            return "git_status_unavailable", "could not parse tracked Git attributes"
        if any(value not in {"unspecified", "unset"} for value in fields[2:-1:3]):
            return "clean_filter_present", "tracked Git filter attributes prevent read-only status inspection"
    return None, None


def validate_pr_sweep_dirty_closeout(
    repo_root: Path, *, ledger_path: Path | None = None, require_clean: bool = False
) -> PrSweepValidationResult:
    """Account for primary-checkout dirt; never equate a ledger with cleanliness."""
    try:
        top_level = _run_git(repo_root, "rev-parse", "--show-toplevel")
        if top_level.returncode != 0 or Path(top_level.stdout.strip()).resolve() != repo_root.resolve():
            return _failure(
                "dirty_closeout", "blocked", "invalid_repo_root", "supplied root is not a worktree top level"
            )
        blocker_code, blocker_message = _git_status_preflight(repo_root)
        if blocker_code is not None and blocker_message is not None:
            return _failure("dirty_closeout", "blocked", blocker_code, blocker_message)
        completed = _run_git(
            repo_root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"
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
            ledgered = _ledger_paths(_read_ledger(ledger_path))
        except (OSError, UnicodeError, ValueError, RecursionError):
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
