"""Installed-wheel smoke for both PR-sweep validators without Agent-Skills."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import skills_sdk
from skills_sdk.validation import validate_pr_sweep_dirty_closeout, validate_recurring_findings


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)


def _ledger(eligible: bool) -> dict[str, object]:
    invariant = "latest head must be validated before merge"
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
                    for number in range(1, 4)
                ],
                "guardrail": {
                    "status": "blocked",
                    "owner": "fixture-owner",
                    "blocker_ref": "issue:fixture",
                    "expires_at": "2026-10-01T00:00:00Z",
                    "next_review_at": "2026-09-30T00:00:00Z",
                },
                "merge_eligible": eligible,
            }
        ],
    }


def main() -> int:
    assert "agent-skills" not in str(Path(skills_sdk.__file__).resolve())
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    with TemporaryDirectory(prefix="sdk-pr-sweep-smoke-") as directory:
        root = Path(directory)
        ledger = root / "recurring.json"
        ledger.write_text(json.dumps(_ledger(False)), encoding="utf-8")
        assert validate_recurring_findings(ledger).status == "pass"
        command = _run(
            sys.executable,
            "-m",
            "skills_sdk.cli.main",
            "verify",
            "recurring-findings",
            str(ledger),
            "--json",
            "--robot",
            cwd=root,
        )
        assert command.returncode == 0 and json.loads(command.stdout)["status"] == "pass"
        ledger.write_text(json.dumps(_ledger(True)), encoding="utf-8")
        assert validate_recurring_findings(ledger).status == "fail"
        assert (
            _run(
                sys.executable,
                "-m",
                "skills_sdk.cli.main",
                "verify",
                "recurring-findings",
                str(ledger),
                "--json",
                "--robot",
                cwd=root,
            ).returncode
            == 2
        )
        ledger.write_text(json.dumps(_ledger(False)), encoding="utf-8")
        assert validate_recurring_findings(ledger).status == "pass"

        repo = root / "repo"
        repo.mkdir()
        assert _run("git", "init", cwd=repo).returncode == 0
        (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
        assert _run("git", "add", "tracked.txt", cwd=repo).returncode == 0
        assert (
            _run(
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.test",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-m",
                "initial",
                cwd=repo,
            ).returncode
            == 0
        )
        assert validate_pr_sweep_dirty_closeout(repo, require_clean=True).status == "pass"
        (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        assert validate_pr_sweep_dirty_closeout(repo, require_clean=True).status == "fail"
        assert (
            _run(
                sys.executable,
                "-m",
                "skills_sdk.cli.main",
                "verify",
                "pr-sweep-dirty-closeout",
                "--repo-root",
                str(repo),
                "--require-clean",
                "--json",
                "--robot",
                cwd=root,
            ).returncode
            == 2
        )
        (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
        assert validate_pr_sweep_dirty_closeout(repo, require_clean=True).status == "pass"
    print("installed PR-sweep API and CLI: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
