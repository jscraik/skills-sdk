"""Portable PR-sweep validators: accepted, rejected, and corrected input."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.pr_sweep import PrSweepDirtyState, PrSweepValidationResult
from skills_sdk.validation import validate_pr_sweep_dirty_closeout, validate_recurring_findings


def _ledger(*, count: int = 3, validated: bool = True, eligible: bool = True) -> dict[str, object]:
    invariant = "latest head must be validated before merge"
    guardrail: dict[str, object] = (
        {
            "status": "validated",
            "artifact_ref": "validator:latest-head",
            "validation_commands": [{"command": "pytest -q", "status": "pass"}],
        }
        if validated
        else {
            "status": "blocked",
            "owner": "fixture-owner",
            "blocker_ref": "issue:fixture",
            "expires_at": "2026-10-01T00:00:00Z",
            "next_review_at": "2026-09-30T00:00:00Z",
        }
    )
    return {
        "schema_version": 1,
        "classes": [
            {
                "finding_class_id": "finding_latest_head_validation",
                "fingerprint_sha256": hashlib.sha256(invariant.encode()).hexdigest(),
                "normalized_invariant": invariant,
                "root_cause": "stale hosted evidence",
                "occurrences": [
                    {
                        "repository": "jscraik/example",
                        "pull_request": number,
                        "evidence_ref": f"https://github.com/jscraik/example/pull/{number}",
                    }
                    for number in range(1, count + 1)
                ],
                "guardrail": guardrail,
                "merge_eligible": eligible,
            }
        ],
    }


def _write_ledger(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "initial",
    )
    return repo


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "skills_sdk.cli.main", "verify", *args, "--json", "--robot"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_recurring_ledger_threshold_and_recovery(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    _write_ledger(path, _ledger(count=2, validated=False))
    accepted = validate_recurring_findings(path)
    assert accepted.status == "pass"
    SchemaRegistry().validate("pr-sweep-validation.v1", accepted.model_dump(mode="json"))

    _write_ledger(path, _ledger(validated=False))
    rejected = validate_recurring_findings(path)
    assert rejected.status == "fail"
    assert "merge_eligible must be false" in rejected.findings[0].message
    assert _cli("recurring-findings", str(path)).returncode == 2

    _write_ledger(path, _ledger(validated=False, eligible=False))
    assert validate_recurring_findings(path).status == "pass"
    command = _cli("recurring-findings", str(path))
    assert command.returncode == 0
    SchemaRegistry().validate("pr-sweep-validation.v1", json.loads(command.stdout))


@pytest.mark.parametrize(
    "defect", ["fingerprint", "duplicate_class", "duplicate_occurrence", "date_format", "unknown_field"]
)
def test_recurring_ledger_rejects_defects_then_recovers(tmp_path: Path, defect: str) -> None:
    path = tmp_path / "ledger.json"
    payload = _ledger()
    row = payload["classes"][0]
    if defect == "fingerprint":
        row["fingerprint_sha256"] = "0" * 64
    elif defect == "duplicate_class":
        payload["classes"].append(dict(row))
    elif defect == "duplicate_occurrence":
        row["occurrences"].append(dict(row["occurrences"][0]))
    elif defect == "date_format":
        row["guardrail"] = _ledger(validated=False)["classes"][0]["guardrail"]
        row["guardrail"]["expires_at"] = "not-a-date"
    else:
        row["unknown"] = True
    _write_ledger(path, payload)
    assert validate_recurring_findings(path).status == "fail"
    _write_ledger(path, _ledger())
    assert validate_recurring_findings(path).status == "pass"


def test_dirty_closeout_accounting_never_waives_clean_requirement(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert validate_pr_sweep_dirty_closeout(repo, require_clean=True).status == "pass"
    (repo / "tracked.txt").write_text("modified\n", encoding="utf-8")
    (repo / "file with space.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    missing = validate_pr_sweep_dirty_closeout(repo)
    assert missing.status == "fail"
    assert {finding.code for finding in missing.findings} == {"dirty_worktree_ledger_required"}
    assert missing.dirty_state is not None
    assert missing.dirty_state.staged_paths == ("tracked.txt",)
    assert missing.dirty_state.untracked_paths == ("file with space.txt",)
    ledger = tmp_path / "dirty.json"
    _write_ledger(ledger, {"dirty_worktree_ledger": [{"path": "tracked.txt"}, {"path": "file with space.txt"}]})
    accounted = validate_pr_sweep_dirty_closeout(repo, ledger_path=ledger)
    assert accounted.status == "pass"
    assert accounted.unledgered_paths == ()
    SchemaRegistry().validate("pr-sweep-validation.v1", accounted.model_dump(mode="json"))
    blocked = validate_pr_sweep_dirty_closeout(repo, ledger_path=ledger, require_clean=True)
    assert blocked.status == "fail"
    assert "primary_worktree_dirty" in {finding.code for finding in blocked.findings}
    assert (
        _cli("pr-sweep-dirty-closeout", "--repo-root", str(repo), "--ledger", str(ledger), "--require-clean").returncode
        == 2
    )


def test_dirty_ledger_rejects_host_paths_without_emitting_them(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "tracked.txt").write_text("modified\n", encoding="utf-8")
    ledger = tmp_path / "dirty.json"
    host_path = str(tmp_path / "private.txt")
    _write_ledger(ledger, {"paths": [host_path, "tracked.txt"]})
    rejected = validate_pr_sweep_dirty_closeout(repo, ledger_path=ledger)
    assert rejected.status == "fail"
    assert "invalid_ledger_path" in {finding.code for finding in rejected.findings}
    assert host_path not in rejected.model_dump_json()
    _write_ledger(ledger, {"paths": ["tracked.txt"]})
    recovered = validate_pr_sweep_dirty_closeout(repo, ledger_path=ledger)
    assert recovered.status == "pass"
    assert recovered.ledgered_paths == ("tracked.txt",)


def test_bare_verify_does_not_succeed_without_running_a_check() -> None:
    command = subprocess.run(
        [sys.executable, "-m", "skills_sdk.cli.main", "verify"], capture_output=True, text=True, check=False
    )
    assert command.returncode == 2
    assert "required" in command.stderr


def test_dirty_closeout_unstaged_rename_and_malformed_ledger(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "tracked.txt").rename(repo / "renamed file.txt")
    state = validate_pr_sweep_dirty_closeout(repo)
    assert state.status == "fail"
    assert state.dirty_state is not None
    assert "tracked.txt" in state.dirty_state.unstaged_paths
    assert "renamed file.txt" in state.dirty_state.untracked_paths
    ledger = tmp_path / "dirty.json"
    ledger.write_text("{", encoding="utf-8")
    assert "ledger_unreadable" in {
        finding.code for finding in validate_pr_sweep_dirty_closeout(repo, ledger_path=ledger).findings
    }
    (repo / "renamed file.txt").rename(repo / "tracked.txt")
    assert validate_pr_sweep_dirty_closeout(repo, require_clean=True).status == "pass"


def test_dirty_closeout_staged_rename_accounts_for_both_paths(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "mv", "tracked.txt", "renamed file.txt")
    result = validate_pr_sweep_dirty_closeout(repo)
    assert result.status == "fail"
    assert result.dirty_state is not None
    assert result.dirty_state.staged_paths == ("renamed file.txt", "tracked.txt")
    ledger = tmp_path / "dirty.json"
    _write_ledger(ledger, {"paths": ["renamed file.txt", "tracked.txt"]})
    assert validate_pr_sweep_dirty_closeout(repo, ledger_path=ledger).status == "pass"
    assert validate_pr_sweep_dirty_closeout(repo, ledger_path=ledger, require_clean=True).status == "fail"


def test_dirty_closeout_git_failure_is_typed_blocker(tmp_path: Path) -> None:
    result = validate_pr_sweep_dirty_closeout(tmp_path / "missing")
    assert result.status == "blocked"
    assert result.findings[0].code == "git_status_unavailable"
    assert str(tmp_path) not in result.model_dump_json()


def test_dirty_closeout_requires_worktree_top_level(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    nested = repo / "nested"
    nested.mkdir()
    (repo / "outside.txt").write_text("dirty\n", encoding="utf-8")
    result = validate_pr_sweep_dirty_closeout(nested, require_clean=True)
    assert result.status == "blocked"
    assert result.findings[0].code == "invalid_repo_root"


def test_deep_ledgers_and_looped_repo_root_return_typed_results(tmp_path: Path) -> None:
    ledger = tmp_path / "deep.json"
    ledger.write_text("[" * 1500 + "0" + "]" * 1500, encoding="utf-8")
    recurring = validate_recurring_findings(ledger)
    assert recurring.status == "fail"
    assert recurring.findings[0].code in {"ledger_unreadable", "ledger_schema"}

    repo = _repo(tmp_path)
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    dirty = validate_pr_sweep_dirty_closeout(repo, ledger_path=ledger)
    assert dirty.status == "fail"
    assert dirty.findings[0].code == "ledger_unreadable"
    blocked = validate_pr_sweep_dirty_closeout(loop)
    assert blocked.status == "blocked"
    assert blocked.findings[0].code == "git_status_unavailable"


@pytest.mark.parametrize(
    "reference",
    ["https://github.com/other/repo/pull/999", "https://github.com/other/repo/actions/runs/999"],
)
def test_recurring_occurrences_bind_pull_identity_and_recover(tmp_path: Path, reference: str) -> None:
    path = tmp_path / "ledger.json"
    payload = _ledger()
    payload["classes"][0]["occurrences"][0]["evidence_ref"] = reference
    _write_ledger(path, payload)
    assert validate_recurring_findings(path).status == "fail"
    _write_ledger(path, _ledger())
    assert validate_recurring_findings(path).status == "pass"


@pytest.mark.parametrize("payload", ['{"schema_version":1,"schema_version":1,"classes":[]}', '{"classes":NaN}'])
def test_recurring_rejects_noncanonical_json(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "ledger.json"
    path.write_text(payload, encoding="utf-8")
    assert validate_recurring_findings(path).findings[0].code == "ledger_unreadable"


def test_recurring_schema_errors_do_not_echo_host_input(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    secret = str(tmp_path / "private-marker")
    _write_ledger(path, {"schema_version": 1, "classes": [], "unexpected": secret})
    result = validate_recurring_findings(path)
    assert result.status == "fail"
    assert secret not in result.model_dump_json()


@pytest.mark.parametrize("reference", ["../private.txt:12", "C:\\private.txt:12"])
def test_recurring_rejects_unsafe_local_evidence(tmp_path: Path, reference: str) -> None:
    path = tmp_path / "ledger.json"
    payload = _ledger()
    payload["classes"][0]["guardrail"]["artifact_ref"] = reference
    _write_ledger(path, payload)
    assert validate_recurring_findings(path).status == "fail"


def test_ledger_reader_rejects_fifo_and_symlink_without_hanging(tmp_path: Path) -> None:
    fifo = tmp_path / "ledger.fifo"
    os.mkfifo(fifo)
    assert validate_recurring_findings(fifo).findings[0].code == "ledger_unreadable"
    source = tmp_path / "source.json"
    _write_ledger(source, _ledger())
    link = tmp_path / "link.json"
    link.symlink_to(source)
    assert validate_recurring_findings(link).findings[0].code == "ledger_unreadable"


def test_dirty_closeout_does_not_run_fsmonitor(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sentinel = tmp_path / "monitor-ran"
    hook = tmp_path / "monitor.sh"
    hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    _git(repo, "config", "core.fsmonitor", str(hook))
    assert validate_pr_sweep_dirty_closeout(repo).status == "pass"
    assert not sentinel.exists()


def test_dirty_closeout_rename_with_unstaged_edit_reports_destination_only(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "mv", "tracked.txt", "renamed.txt")
    (repo / "renamed.txt").write_text("edited\n", encoding="utf-8")
    result = validate_pr_sweep_dirty_closeout(repo)
    assert result.dirty_state is not None
    assert result.dirty_state.unstaged_paths == ("renamed.txt",)
    assert result.dirty_state.staged_paths == ("renamed.txt", "tracked.txt")


def test_dirty_result_model_rejects_false_pass_accounting() -> None:
    with pytest.raises(ValueError):
        PrSweepValidationResult(
            kind="dirty_closeout",
            status="pass",
            dirty_state=PrSweepDirtyState(unstaged_paths=("changed.txt",), dirty_paths=("changed.txt",)),
        )


def test_dirty_ledger_ignores_unrecognized_notes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "tracked.txt").write_text("edited\n", encoding="utf-8")
    ledger = tmp_path / "dirty.json"
    _write_ledger(ledger, {"notes": ["https://example.invalid/path"], "paths": ["tracked.txt"]})
    result = validate_pr_sweep_dirty_closeout(repo, ledger_path=ledger)
    assert result.status == "pass"
    assert result.ledgered_paths == ("tracked.txt",)


def test_dirty_closeout_sees_submodule_even_when_repo_ignores_it(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    parent = tmp_path / "parent"
    parent.mkdir()
    _git(parent, "init")
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", str(source), "module"],
        cwd=parent,
        check=True,
        capture_output=True,
        text=True,
    )
    _git(parent, "add", ".")
    _git(
        parent,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "submodule",
    )
    _git(parent, "config", "submodule.module.ignore", "all")
    (parent / "module" / "tracked.txt").write_text("changed\n", encoding="utf-8")
    result = validate_pr_sweep_dirty_closeout(parent, require_clean=True)
    assert result.status == "fail"
    assert result.dirty_state is not None
    assert "module" in result.dirty_state.dirty_paths
