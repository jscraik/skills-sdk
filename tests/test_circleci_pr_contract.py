"""Exercise the CircleCI PR guard with controlled Git and API fixtures."""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest
from test_validation_performance import ROOT, _fixture_environment, _git, _repository


def _circleci_fixture(tmp_path: Path, docs_only: bool = False) -> tuple[Path, dict[str, str], str]:
    """Create real Git merge refs, trusted controls and a bounded metadata fixture."""
    root = tmp_path / "checkout"
    root.mkdir()
    _repository(root)
    for relative in (
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/scripts/validate_pr_template_body.py",
        "scripts/validation_scope.py",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "fixture trusted controls")
    base = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/heads/main", base)
    _git(root, "update-ref", "-d", "refs/remotes/origin/main")
    _git(root, "checkout", "-b", "fixture-head")
    if docs_only:
        (root / "README.md").write_text("# Revised documentation\n")
    else:
        (root / ".github/scripts/validate_pr_template_body.py").write_text("raise SystemExit(99)\n")
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "fixture untrusted candidate validator")
    head = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-b", "fixture-base", base)
    _git(root, "-c", "commit.gpgsign=false", "merge", "--no-ff", "--no-edit", "fixture-head")
    merge = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/pull/52/merge", merge)
    _git(root, "checkout", "--detach", head)
    _git(root, "remote", "add", "origin", str(root))
    validator = runpy.run_path(str(ROOT / ".github/scripts/validate_pr_template_body.py"))
    body = (ROOT / ".github/PULL_REQUEST_TEMPLATE.md").read_text().replace("- [ ]", "- [x]")
    body = validator["FIELD_LINE_RE"].sub(
        lambda match: (
            match.group(0)
            if match.group("label") == "Command" or match.group("value").strip()
            else f"- {match.group('label')}: repo-relative evidence"
        ),
        body,
    )
    body = body.replace(
        "- Regression coverage: repo-relative evidence",
        "- Regression coverage: focused proof\n- Command: `bash scripts/validate-repository.sh` -> pass",
    )
    metadata = tmp_path / "pr.json"
    metadata.write_text(
        json.dumps(
            {
                "state": "open",
                "head": {"sha": head},
                "base": {"sha": base, "ref": "main", "repo": {"full_name": "fixture/sdk"}},
                "mergeable": True,
                "merge_commit_sha": merge,
                "body": body,
            }
        )
    )
    main_metadata = tmp_path / "main.json"
    main_metadata.write_text(json.dumps({"ref": "refs/heads/main", "object": {"type": "commit", "sha": base}}))
    binaries = tmp_path / "bin"
    binaries.mkdir()
    curl = binaries / "curl"
    curl.write_text(
        "#!/usr/bin/env python3\nimport json, os, subprocess, sys\nfrom pathlib import Path\n"
        "if os.environ.get('CI_METADATA_FAILURE'): sys.exit(22)\n"
        "if sys.argv[-1].endswith('/git/ref/heads/main'):\n"
        " print(Path(os.environ['CI_MAIN_METADATA']).read_text()); sys.exit(0)\n"
        "p=json.load(open(os.environ['CI_METADATA']))\n"
        "if os.environ.get('CI_READY_SHA'):\n"
        " counter=Path(os.environ['CI_METADATA']+'.ready-calls')\n"
        " calls=int(counter.read_text())+1 if counter.exists() else 1\n"
        " counter.write_text(str(calls))\n"
        " if calls >= 2: p['mergeable']=True; p['merge_commit_sha']=os.environ['CI_READY_SHA']\n"
        "if os.environ.get('CI_FINAL_CHANGE'):\n"
        " counter=Path(os.environ['CI_METADATA']+'.calls')\n"
        " calls=int(counter.read_text())+1 if counter.exists() else 1\n"
        " counter.write_text(str(calls))\n"
        " if calls >= 3:\n"
        "  change=os.environ['CI_FINAL_CHANGE']\n"
        "  if change == 'body': p['body']=''\n"
        "  if change == 'head': p['head']['sha']='f'*40\n"
        "  if change == 'api-merge': p['merge_commit_sha']='f'*40\n"
        "  if change == 'base-ref': p['base']['ref']='other'\n"
        "  if change == 'base-repo': p['base']['repo']['full_name']='other/sdk'\n"
        "  if change == 'api-main':\n"
        "   main=json.load(open(os.environ['CI_MAIN_METADATA']))\n"
        "   main['object']['sha']=os.environ['CI_NEXT_REF']\n"
        "   Path(os.environ['CI_MAIN_METADATA']).write_text(json.dumps(main))\n"
        "  if change == 'main-trailing':\n"
        "   path=Path(os.environ['CI_MAIN_METADATA'])\n"
        "   path.write_text(path.read_text() + ' {')\n"
        "  if change in ('main', 'merge'):\n"
        "   ref='refs/heads/main' if change == 'main' else 'refs/pull/52/merge'\n"
        "   subprocess.run(['git', 'update-ref', ref, os.environ['CI_NEXT_REF']], check=True)\n"
        "assert not any('Authorization' in arg for arg in sys.argv)\n"
        "print(json.dumps(p))\n"
    )
    curl.chmod(0o755)
    sleep = binaries / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    environment = {
        **_fixture_environment(),
        "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
        "CI_METADATA": str(metadata),
        "CI_MAIN_METADATA": str(main_metadata),
        "BASH_ENV": str(tmp_path / "bash-env"),
        "CIRCLE_PULL_REQUEST": "https://github.com/fixture/sdk/pull/52",
        "CIRCLE_PROJECT_USERNAME": "fixture",
        "CIRCLE_PROJECT_REPONAME": "sdk",
        "CIRCLE_SHA1": head,
        "CIRCLE_BRANCH": "fixture-head",
    }
    return root, environment, merge


def _change_circleci_refs(root: Path, environment: dict[str, str], case: str, base: str, head: str) -> None:
    """Change only the synthetic origin refs while retaining independent API metadata."""
    if case in {"forged-merge-tree", "wrong-merge-head"}:
        second_parent = head if case == "forged-merge-tree" else f"{base}^1"
        wrong_merge = _git(
            root,
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            f"{base}^{{tree}}",
            "-p",
            base,
            "-p",
            second_parent,
            "-m",
            "fixture wrong merge",
        )
        _git(root, "update-ref", "refs/pull/52/merge", wrong_merge)
        return
    next_ref = _git(
        root, "-c", "commit.gpgsign=false", "commit-tree", f"{base}^{{tree}}", "-p", base, "-m", "fixture moved ref"
    )
    if case == "stale-merge":
        _git(root, "update-ref", "refs/heads/main", next_ref)
        Path(environment["CI_MAIN_METADATA"]).write_text(
            json.dumps({"ref": "refs/heads/main", "object": {"type": "commit", "sha": next_ref}})
        )
    elif case == "forged-origin-main":
        forged_merge = _git(
            root,
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            f"{base}^{{tree}}",
            "-p",
            next_ref,
            "-p",
            head,
            "-m",
            "fixture forged origin merge",
        )
        _git(root, "update-ref", "refs/heads/main", next_ref)
        _git(root, "update-ref", "refs/pull/52/merge", forged_merge)
    else:
        environment["CI_FINAL_CHANGE"] = case.removeprefix("changed-")
        environment["CI_NEXT_REF"] = next_ref


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "docs",
        "main",
        "missing-pr",
        "invalid-body",
        "changed-body",
        "wrong-head",
        "stale-api-base",
        "wrong-base-ref",
        "wrong-base-repo",
        "missing-base-repo",
        "wrong-merge",
        "wrong-merge-head",
        "forged-merge-tree",
        "unready-merge",
        "merge-computing-recovers",
        "unmergeable",
        "invalid-merge-sha",
        "bad-main-ref",
        "bad-main-type",
        "bad-main-sha",
        "bad-main-json",
        "bad-main-trailing",
        "stale-merge",
        "forged-origin-main",
        "changed-head",
        "changed-base-ref",
        "changed-base-repo",
        "changed-main",
        "changed-api-main",
        "changed-main-trailing",
        "changed-api-merge",
        "changed-merge",
        "api-error",
    ],
)
def test_circleci_operator_path_uses_trusted_base_and_verified_merge(tmp_path: Path, case: str) -> None:
    """Execute the production shell route with real Git and controlled API responses."""
    root, environment, merge = _circleci_fixture(tmp_path, docs_only=case == "docs")
    initial = _git(root, "rev-parse", "HEAD")
    metadata = Path(environment["CI_METADATA"])
    data = json.loads(metadata.read_text())
    actual_base = data["base"]["sha"]
    if case == "invalid-body":
        data["body"] = ""
    elif case == "changed-body":
        environment["CI_FINAL_CHANGE"] = "body"
    elif case == "api-error":
        environment["CI_METADATA_FAILURE"] = "1"
    elif case == "wrong-head":
        data["head"]["sha"] = "f" * 40
    elif case == "stale-api-base":
        data["base"]["sha"] = _git(root, "rev-parse", f"{actual_base}^1")
    elif case == "wrong-base-ref":
        data["base"]["ref"] = "other"
    elif case == "wrong-base-repo":
        data["base"]["repo"]["full_name"] = "other/sdk"
    elif case == "missing-base-repo":
        del data["base"]["repo"]
    elif case == "unready-merge":
        data["mergeable"] = None
        data["merge_commit_sha"] = None
    elif case == "merge-computing-recovers":
        data["mergeable"] = None
        data["merge_commit_sha"] = None
        environment["CI_READY_SHA"] = merge
    elif case == "unmergeable":
        data["mergeable"] = False
    elif case == "invalid-merge-sha":
        data["merge_commit_sha"] = "invalid"
    elif case.startswith("bad-main-"):
        main_path = Path(environment["CI_MAIN_METADATA"])
        main_data = json.loads(main_path.read_text())
        if case == "bad-main-ref":
            main_data["ref"] = "refs/heads/other"
        elif case == "bad-main-type":
            main_data["object"]["type"] = "tag"
        elif case == "bad-main-sha":
            main_data["object"]["sha"] = "invalid"
        if case == "bad-main-json":
            main_path.write_text("{")
        elif case == "bad-main-trailing":
            main_path.write_text(json.dumps(main_data) + " {")
        else:
            main_path.write_text(json.dumps(main_data))
    elif case == "wrong-merge":
        _git(root, "update-ref", "refs/pull/52/merge", initial)
    elif case in {
        "forged-merge-tree",
        "wrong-merge-head",
        "stale-merge",
        "forged-origin-main",
        "changed-main",
        "changed-api-main",
        "changed-merge",
    }:
        _change_circleci_refs(root, environment, case, actual_base, initial)
        if case in {"wrong-merge-head", "forged-origin-main"}:
            data["merge_commit_sha"] = _git(root, "rev-parse", "refs/pull/52/merge")
    elif case.startswith("changed-"):
        environment["CI_FINAL_CHANGE"] = case.removeprefix("changed-")
    elif case in {"main", "missing-pr"}:
        environment["CIRCLE_PULL_REQUEST"] = ""
        if case == "main":
            environment["CIRCLE_BRANCH"] = "main"
    metadata.write_text(json.dumps(data))
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/circleci_pr_contract.sh")],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    accepted = {"valid", "docs", "main", "stale-api-base", "merge-computing-recovers"}
    if case in accepted:
        assert result.returncode == 0, result.stderr
    elif case == "api-error":
        assert result.returncode == 22, result.stderr
    else:
        assert result.returncode != 0, result.stderr
    if case == "forged-origin-main":
        assert "Fetched main does not match GitHub main" in result.stderr
    if case == "wrong-merge-head":
        assert "PR merge parents do not match live base and head" in result.stderr
    if case == "forged-merge-tree":
        assert "Fetched merge does not match GitHub test merge" in result.stderr
    if case in accepted:
        assert _git(root, "rev-parse", "HEAD") == (initial if case == "main" else merge)
        scope = "docs" if case == "docs" else "full"
        expected = f"export SDK_CI_SCOPE={scope}\n"
        if case != "main":
            expected += f"export SDK_CI_BASE_SHA={actual_base}\n"
        assert Path(environment["BASH_ENV"]).read_text() == expected
        if case != "main":
            assert _git(root, "rev-parse", "refs/remotes/origin/main") == actual_base
    else:
        assert _git(root, "rev-parse", "HEAD") == initial
        assert not Path(environment["BASH_ENV"]).exists()
