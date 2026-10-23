"""Exact docs classification, fail-closed phases and worker isolation proof."""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.validation_scope import git_environment, validation_scope
from scripts.validation_scope import main as validation_main

ROOT = Path(__file__).resolve().parents[1]


def _fixture_environment() -> dict[str, str]:
    """Keep disposable checkouts independent of the caller's CI bootstrap."""
    environment = git_environment()
    for name in ("BASH_ENV", "SDK_CI_BASE_SHA", "SDK_CI_SCOPE", "CIRCLE_BRANCH", "CIRCLE_SHA1"):
        environment.pop(name, None)
    return environment


def _git(root: Path, *arguments: str) -> str:
    """Run an isolated fixture Git command and return its stripped text output."""
    environment = _fixture_environment()
    return subprocess.run(
        ["git", *arguments], cwd=root, env=environment, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repository(root: Path) -> str:
    """Initialize a prose fixture and return its commit registered as accepted main."""
    _git(root, "init")
    _git(root, "config", "user.name", "Validation fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    (root / "README.md").write_text("# Fixture\n")
    _git(root, "add", "README.md")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "fixture baseline")
    base = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/main", base)
    return base


@pytest.mark.parametrize("relative", ["README.md", "docs/guide.md", "docs/nested/guide.rst"])
def test_prose_change_selects_docs_and_source_change_restores_full(tmp_path: Path, relative: str) -> None:
    """Verify dirty and committed prose select docs until executable source is added."""
    base = _repository(tmp_path)
    prose = tmp_path / relative
    prose.parent.mkdir(parents=True, exist_ok=True)
    prose.write_text("# Corrected guidance\n")
    assert validation_scope(tmp_path, base, base) == "docs"
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture prose")
    head = _git(tmp_path, "rev-parse", "HEAD")
    assert validation_scope(tmp_path, base, head) == "docs"
    (tmp_path / "runtime.py").write_text("value = 1\n")
    assert validation_scope(tmp_path, base, head) == "full"


@pytest.mark.parametrize(
    "relative",
    [
        "AGENTS.md",
        "CODESTYLE.md",
        "CONTRIBUTING.md",
        ".github/template.md",
        "docs/a.py",
        "docs/standards.md",
        "docs/AGENTS.md",
    ],
)
def test_policy_or_executable_changes_require_full_validation(tmp_path: Path, relative: str) -> None:
    """Verify policy files and executable source cannot select the prose route."""
    base = _repository(tmp_path)
    source = tmp_path / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("changed\n")
    assert validation_scope(tmp_path, base, base) == "full"


def test_empty_stale_head_symlink_and_mode_changes_do_not_select_docs(tmp_path: Path) -> None:
    """Reject stale heads and keep empty, executable-mode, or symlink changes on full proof."""
    base = _repository(tmp_path)
    assert validation_scope(tmp_path, base, base) == "full"
    prose = tmp_path / "README.md"
    prose.write_text("changed\n")
    prose.chmod(0o755)
    assert validation_scope(tmp_path, base, base) == "full"
    prose.chmod(0o644)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture change")
    with pytest.raises(ValueError, match="current checkout"):
        validation_scope(tmp_path, base, base)
    head = _git(tmp_path, "rev-parse", "HEAD")
    prose.unlink()
    prose.symlink_to(tmp_path / "missing")
    assert validation_scope(tmp_path, base, head) == "full"


def test_missing_base_is_blocked_and_corrected_identity_recovers(tmp_path: Path) -> None:
    """Verify an unknown base blocks classification and a valid base restores docs scope."""
    base = _repository(tmp_path)
    (tmp_path / "README.md").write_text("changed\n")
    with pytest.raises(subprocess.CalledProcessError):
        validation_scope(tmp_path, "missing-reference", base)
    assert validation_scope(tmp_path, base, base) == "docs"


def test_unaccepted_base_and_staged_mode_cannot_hide_executable_changes(tmp_path: Path) -> None:
    """Reject unaccepted bases and require full proof for staged executable modes."""
    base = _repository(tmp_path)
    (tmp_path / "runtime.py").write_text("value = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture code")
    head = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "README.md").write_text("new guidance\n")
    with pytest.raises(subprocess.CalledProcessError):
        validation_scope(tmp_path, head, head)
    assert validation_scope(tmp_path, base, head) == "full"
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", head)
    _git(tmp_path, "update-index", "--chmod=+x", "README.md")
    assert not (tmp_path / "README.md").stat().st_mode & 0o111
    assert validation_scope(tmp_path, head, head) == "full"
    _git(tmp_path, "update-index", "--chmod=-x", "README.md")
    assert validation_scope(tmp_path, head, head) == "docs"


@pytest.mark.parametrize("change", ["rename", "canceled_worktree"])
def test_staged_source_changes_cannot_hide_in_docs_or_worktree(change: str, tmp_path: Path) -> None:
    """Keep staged source edits visible despite prose renames or canceled worktree edits."""
    _repository(tmp_path)
    source = tmp_path / "runtime.py"
    source.write_text("value = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture code")
    base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", base)
    (tmp_path / "README.md").write_text("new guidance\n")
    if change == "rename":
        (tmp_path / "docs").mkdir()
        _git(tmp_path, "mv", "runtime.py", "docs/guide.md")
    else:
        source.write_text("value = 2\n")
        _git(tmp_path, "add", "runtime.py")
        source.write_text("value = 1\n")
    assert validation_scope(tmp_path, base, base) == "full"


@pytest.mark.parametrize(
    "flags", [("--assume-unchanged",), ("--skip-worktree",), ("--assume-unchanged", "--skip-worktree")]
)
def test_hidden_index_flags_require_full_proof_without_mutating_index(tmp_path: Path, flags: tuple[str, ...]) -> None:
    """Verify hidden index flags force full proof and clearing them permits recovery."""
    _repository(tmp_path)
    source = tmp_path / "runtime.py"
    source.write_text("value = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture code")
    head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", head)
    (tmp_path / "README.md").write_text("new guidance\n")
    command = [sys.executable, str(ROOT / "scripts/validation_scope.py"), "--base", head, "--head", head]
    assert validation_scope(tmp_path, head, head) == "docs"
    for flag in flags:
        _git(tmp_path, "update-index", flag, "runtime.py")
    source.write_text("value = 2\n")
    index = tmp_path / ".git/index"
    before = index.read_bytes()
    assert validation_scope(tmp_path, head, head) == "full"
    result = subprocess.run(command, cwd=tmp_path, check=False, capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == "full"
    assert index.read_bytes() == before
    invalid = subprocess.run([*command[:-1], "missing-head"], cwd=tmp_path, check=False, capture_output=True, text=True)
    assert invalid.returncode == 2 and "validation scope blocked" in invalid.stderr
    for flag in flags:
        _git(tmp_path, "update-index", flag.replace("--", "--no-", 1), "runtime.py")
    assert validation_scope(tmp_path, head, head) == "full"
    source.write_text("value = 1\n")
    assert validation_scope(tmp_path, head, head) == "docs"
    for flag in flags:
        _git(tmp_path, "update-index", flag, "runtime.py")
    assert validation_scope(tmp_path, head, head) == "full"
    for flag in flags:
        _git(tmp_path, "update-index", flag.replace("--", "--no-", 1), "runtime.py")
    recovered = subprocess.run(command, cwd=tmp_path, check=False, capture_output=True, text=True)
    assert recovered.returncode == 0 and recovered.stdout.strip() == "docs"


@pytest.mark.parametrize("file_mode", ["true", "false"])
@pytest.mark.parametrize("mode", [0o755, 0o654, 0o645])
def test_worktree_executable_mode_requires_full_even_when_git_ignores_it(
    tmp_path: Path, file_mode: str, mode: int
) -> None:
    """Detect physical mode drift without changing the caller's index or Git configuration."""
    _repository(tmp_path)
    source = tmp_path / "runtime.py"
    source.write_text("value = 1\n")
    source.chmod(0o644)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture mode baseline")
    head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", head)
    _git(tmp_path, "config", "core.fileMode", file_mode)
    (tmp_path / "README.md").write_text("new guidance\n")
    command = [sys.executable, str(ROOT / "scripts/validation_scope.py"), "--base", head, "--head", head]
    assert validation_scope(tmp_path, head, head) == "docs"
    source.chmod(mode)
    if file_mode == "false":
        assert _git(tmp_path, "diff", "--name-only") == "README.md"
    index, config = tmp_path / ".git/index", tmp_path / ".git/config"
    before = index.read_bytes(), config.read_bytes()
    assert validation_scope(tmp_path, head, head) == "full"
    rejected = subprocess.run(
        command, cwd=tmp_path, env=_fixture_environment(), capture_output=True, text=True, check=False
    )
    assert rejected.returncode == 0 and rejected.stdout.strip() == "full", rejected.stderr
    assert (index.read_bytes(), config.read_bytes()) == before
    source.chmod(0o644)
    assert validation_scope(tmp_path, head, head) == "docs"
    recovered = subprocess.run(
        command, cwd=tmp_path, env=_fixture_environment(), capture_output=True, text=True, check=False
    )
    assert recovered.returncode == 0 and recovered.stdout.strip() == "docs", recovered.stderr
    assert (index.read_bytes(), config.read_bytes()) == before


def test_worktree_metadata_error_blocks_cli_and_corrected_access_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fail closed on a controlled metadata-access error without modifying caller state."""
    _repository(tmp_path)
    source = tmp_path / "runtime.py"
    source.write_text("value = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture metadata baseline")
    head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", head)
    (tmp_path / "README.md").write_text("new guidance\n")
    index, config = tmp_path / ".git/index", tmp_path / ".git/config"
    before = index.read_bytes(), config.read_bytes()
    original = Path.lstat

    def denied(path: Path) -> os.stat_result:
        if path == source:
            raise PermissionError("fixture metadata access denied")
        return original(path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["validation_scope", "--base", head, "--head", head])
    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", denied)
        with pytest.raises(SystemExit) as blocked:
            validation_main()
        assert blocked.value.code == 2
    assert "validation scope blocked: fixture metadata access denied" in capsys.readouterr().err
    assert (index.read_bytes(), config.read_bytes()) == before
    assert validation_main() == 0
    assert capsys.readouterr().out.strip() == "docs"
    assert (index.read_bytes(), config.read_bytes()) == before


@pytest.mark.parametrize("baseline_choice", ["current", "historical"])
def test_base_advanced_after_branch_creation_falls_back_to_full(tmp_path: Path, baseline_choice: str) -> None:
    """Require full proof when accepted main has advanced outside the candidate ancestry."""
    base = _repository(tmp_path)
    (tmp_path / "README.md").write_text("branch guidance\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture candidate")
    head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-b", "advanced-main", base)
    (tmp_path / "runtime.py").write_text("value = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture main")
    advanced = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", advanced)
    _git(tmp_path, "checkout", "--detach", head)
    declared_base = advanced if baseline_choice == "current" else base
    assert validation_scope(tmp_path, declared_base, head) == "full"
    command = [sys.executable, str(ROOT / "scripts/validation_scope.py"), "--base", declared_base, "--head", head]
    rejected = subprocess.run(
        command, cwd=tmp_path, env=_fixture_environment(), capture_output=True, text=True, check=False
    )
    assert rejected.returncode == 0 and rejected.stdout.strip() == "full", rejected.stderr
    _git(tmp_path, "-c", "commit.gpgsign=false", "merge", "--no-edit", advanced)
    rebound = _git(tmp_path, "rev-parse", "HEAD")
    index_before = (tmp_path / ".git" / "index").read_bytes()
    assert validation_scope(tmp_path, advanced, rebound) == "docs"
    corrected = [sys.executable, str(ROOT / "scripts/validation_scope.py"), "--base", advanced, "--head", rebound]
    recovered = subprocess.run(
        corrected, cwd=tmp_path, env=_fixture_environment(), capture_output=True, text=True, check=False
    )
    assert recovered.returncode == 0 and recovered.stdout.strip() == "docs", recovered.stderr
    assert (tmp_path / ".git" / "index").read_bytes() == index_before


def test_inherited_git_selectors_do_not_mutate_or_classify_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify inherited Git selectors cannot redirect fixture writes or classification."""
    caller, fixture = tmp_path / "caller", tmp_path / "fixture"
    caller.mkdir()
    fixture.mkdir()
    caller_head = _repository(caller)
    sentinel = tmp_path / "caller-index"
    sentinel.write_bytes(b"caller-owned index sentinel")
    for key, value in {
        "GIT_DIR": str(caller / ".git"),
        "GIT_WORK_TREE": str(caller),
        "GIT_COMMON_DIR": str(caller / ".git"),
        "GIT_INDEX_FILE": str(sentinel),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.worktree",
        "GIT_CONFIG_VALUE_0": str(caller),
    }.items():
        monkeypatch.setenv(key, value)
    head = _repository(fixture)
    (fixture / "README.md").write_text("fixture guidance\n")
    assert validation_scope(fixture, head, head) == "docs"
    assert _git(caller, "rev-parse", "HEAD") == caller_head
    assert not _git(caller, "status", "--porcelain")
    assert sentinel.read_bytes() == b"caller-owned index sentinel"


def test_phase_reports_failure_without_running_later_phases(tmp_path: Path) -> None:
    """Verify a failed phase reports its status and prevents later phases from running."""
    tools = tmp_path / "bin"
    tools.mkdir()
    mise = tools / "mise"
    mise.write_text("#!/bin/sh\nprintf 'fixture command: %s\\n' \"$*\"\nexit 7\n")
    mise.chmod(0o755)
    result = subprocess.run(
        ["bash", "scripts/validate-repository.sh"],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 7
    assert "finish schemas status=7 elapsed_seconds=" in result.stdout
    assert "start tests" not in result.stdout and "start installed" not in result.stdout


def test_classifier_cli_accepts_rejects_and_recovers(tmp_path: Path) -> None:
    """Exercise CLI scope transitions and the error exit for an unknown head."""
    head = _repository(tmp_path)
    prose = tmp_path / "README.md"
    prose.write_text("new guidance\n")
    command = [sys.executable, str(ROOT / "scripts/validation_scope.py"), "--base", head, "--head", head]
    accepted = subprocess.run(command, cwd=tmp_path, check=False, capture_output=True, text=True)
    assert accepted.returncode == 0 and accepted.stdout.strip() == "docs"
    source = tmp_path / "runtime.py"
    source.write_text("value = 1\n")
    rejected = subprocess.run(command, cwd=tmp_path, check=False, capture_output=True, text=True)
    assert rejected.returncode == 0 and rejected.stdout.strip() == "full"
    source.unlink()
    recovered = subprocess.run(command, cwd=tmp_path, check=False, capture_output=True, text=True)
    assert recovered.returncode == 0 and recovered.stdout.strip() == "docs"
    invalid = subprocess.run([*command[:-1], "missing-head"], cwd=tmp_path, check=False, capture_output=True, text=True)
    assert invalid.returncode == 2 and "validation scope blocked" in invalid.stderr


@pytest.mark.parametrize("argument", ["unknown", "--skip-tests"])
def test_unknown_phase_is_rejected(argument: str) -> None:
    """Verify unsupported phase arguments exit with a usage error."""
    result = subprocess.run(
        ["bash", "scripts/validate-repository.sh", argument], cwd=ROOT, capture_output=True, check=False
    )
    assert result.returncode == 2


def test_parallel_workers_preserve_isolation_and_propagate_failure(tmp_path: Path) -> None:
    """Verify two workers isolate paths and environment changes and propagate test failure."""
    source = tmp_path / "test_isolation.py"
    source.write_text(
        "import os\nimport pytest\n"
        "@pytest.mark.parametrize('number', range(8))\n"
        "def test_isolated(number, tmp_path, monkeypatch):\n"
        "    assert 'SDK_ISOLATION_FIXTURE' not in os.environ\n"
        "    monkeypatch.setenv('SDK_ISOLATION_FIXTURE', str(number))\n"
        "    path = tmp_path / 'same-name.txt'\n"
        "    assert not path.exists()\n"
        "    path.write_text(str(number))\n"
        "    assert path.read_text() == str(number)\n"
    )
    command = [sys.executable, "-m", "pytest", "-n", "2", "--dist", "load", "-q", str(source)]
    passed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert passed.returncode == 0 and "8 passed" in passed.stdout
    source.write_text(source.read_text() + "\ndef test_failure():\n    assert False\n")
    failed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert failed.returncode == 1 and "1 failed, 8 passed" in failed.stdout
    assert "SDK_ISOLATION_FIXTURE" not in os.environ


def test_hosted_docs_classification_uses_trusted_base_and_pushes_run_full() -> None:
    """Check trusted-base workflow routing and preservation of the full validation phases."""
    workflow = (ROOT / ".circleci/config.yml").read_text()
    steps = yaml.safe_load(workflow)["jobs"]["validate"]["steps"]
    docs_step = next(
        step["run"]
        for step in steps
        if isinstance(step, dict) and step.get("run", {}).get("name") == "Documentation-dependent contract tests"
    )
    assert 'if [[ "$SDK_CI_SCOPE" == docs ]]' in docs_step["command"]
    contract = (ROOT / "scripts/circleci_pr_contract.sh").read_text()
    assert 'git show "$BASE_SHA:scripts/validation_scope.py"' in contract
    assert "scope=full" in contract
    assert 'if [[ "$SDK_CI_SCOPE" != docs ]]' in workflow
    for phase in ("quality", "tests", "build", "installed", "diff"):
        assert f"bash scripts/validate-repository.sh {phase}" in workflow
    assert "bash scripts/validate-repository.sh docs-tests" in workflow
    wrapper = (ROOT / "scripts/validate-repository.sh").read_text()
    assert 'phase="${1:-all}"' in wrapper and "pytest -n 2 --dist load --durations=25" in wrapper
    assert "tests/test_public_repository_boundary.py tests/test_skill_validation_architecture.py" in wrapper


def _hosted_classification(root: Path, runner: Path, base: str, head: str) -> subprocess.CompletedProcess[str]:
    """Execute the real hosted classification fragment without changing the validation tree."""
    command = (ROOT / "scripts/circleci_pr_contract.sh").read_text()
    assert "git checkout --detach refs/ci/pr-merge" in command
    fragment = command[command.index('if [[ -f "$classifier" ]]; then') : command.index('echo "scope=$scope"')]
    runner.mkdir()
    classifier = runner / "trusted-classifier.py"
    shutil.copyfile(ROOT / "scripts/validation_scope.py", classifier)
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", fragment + 'printf "%s\\n" "$scope"'],
        cwd=root,
        env={
            **_fixture_environment(),
            "RUNNER_TEMP": str(runner),
            "classifier": str(classifier),
            "BASE_SHA": base,
            "HEAD_SHA": head,
        },
        capture_output=True,
        text=True,
        check=False,
    )


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
    metadata.write_text(json.dumps({"state": "open", "head": {"sha": head}, "base": {"sha": base}, "body": body}))
    binaries = tmp_path / "bin"
    binaries.mkdir()
    curl = binaries / "curl"
    curl.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "if os.environ.get('CI_METADATA_FAILURE'): sys.exit(22)\n"
        "p=json.load(open(os.environ['CI_METADATA']))\n"
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
        "BASH_ENV": str(tmp_path / "bash-env"),
        "CIRCLE_PULL_REQUEST": "https://github.com/fixture/sdk/pull/52",
        "CIRCLE_PROJECT_USERNAME": "fixture",
        "CIRCLE_PROJECT_REPONAME": "sdk",
        "CIRCLE_SHA1": head,
        "CIRCLE_BRANCH": "fixture-head",
    }
    return root, environment, merge


@pytest.mark.parametrize(
    "case",
    ["valid", "docs", "main", "missing-pr", "invalid-body", "wrong-head", "wrong-base", "wrong-merge", "api-error"],
)
def test_circleci_operator_path_uses_trusted_base_and_verified_merge(tmp_path: Path, case: str) -> None:
    """Execute the production shell route with real Git and controlled API responses."""
    root, environment, merge = _circleci_fixture(tmp_path, docs_only=case == "docs")
    initial = _git(root, "rev-parse", "HEAD")
    metadata = Path(environment["CI_METADATA"])
    data = json.loads(metadata.read_text())
    if case == "invalid-body":
        data["body"] = ""
    elif case == "api-error":
        environment["CI_METADATA_FAILURE"] = "1"
    elif case == "wrong-head":
        data["head"]["sha"] = "f" * 40
    elif case == "wrong-base":
        data["base"]["sha"] = initial
    elif case == "wrong-merge":
        _git(root, "update-ref", "refs/pull/52/merge", initial)
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
    expected_status = 0 if case in {"valid", "docs", "main"} else 22 if case == "api-error" else 1
    assert result.returncode == expected_status, result.stderr
    if case in {"valid", "docs", "main"}:
        assert _git(root, "rev-parse", "HEAD") == (initial if case == "main" else merge)
        scope = "docs" if case == "docs" else "full"
        expected = f"export SDK_CI_SCOPE={scope}\n"
        if case != "main":
            expected += f"export SDK_CI_BASE_SHA={data['base']['sha']}\n"
        assert Path(environment["BASH_ENV"]).read_text() == expected
        if case != "main":
            assert _git(root, "rev-parse", "refs/remotes/origin/main") == data["base"]["sha"]
    else:
        assert _git(root, "rev-parse", "HEAD") == initial
        assert not Path(environment["BASH_ENV"]).exists()


@pytest.mark.parametrize("state", ["committed", "staged", "working-tree", "clean", "bad-base"])
def test_diff_phase_checks_committed_staged_and_working_tree_changes(
    tmp_path: Path, state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the real diff phase against clean and whitespace-damaged isolated checkouts."""
    base = _repository(tmp_path)
    inherited = tmp_path / "caller-bootstrap"
    inherited.write_text("export SDK_CI_BASE_SHA=unrelated-caller-revision\n")
    monkeypatch.setenv("BASH_ENV", str(inherited))
    monkeypatch.setenv("SDK_CI_BASE_SHA", "unrelated-caller-revision")
    if state not in {"clean", "bad-base"}:
        (tmp_path / "README.md").write_text("trailing whitespace  \n")
        if state != "working-tree":
            _git(tmp_path, "add", ".")
        if state == "committed":
            _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture whitespace")
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/validate-repository.sh"), "diff"],
        cwd=tmp_path,
        env={**_fixture_environment(), "SDK_CI_BASE_SHA": "missing" if state == "bad-base" else base},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (state == "clean"), result.stdout + result.stderr


@pytest.mark.parametrize("case", ["main-clean", "main-damage", "root-clean", "root-damage", "parent-clean"])
def test_diff_default_comparisons_cover_main_pushes_and_root_commits(tmp_path: Path, case: str) -> None:
    """Check main's full tree, root commits and the local first-parent fallback."""
    _repository(tmp_path)
    if case.endswith("damage"):
        (tmp_path / "README.md").write_text("trailing whitespace  \n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "--amend", "--no-edit")
    if not case.startswith("root"):
        (tmp_path / "next.md").write_text("clean final commit\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture clean tip")
    environment = _fixture_environment()
    environment.pop("SDK_CI_BASE_SHA", None)
    environment["CIRCLE_BRANCH"] = "main" if case.startswith("main") else "fixture"
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/validate-repository.sh"), "diff"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is not case.endswith("damage"), result.stdout + result.stderr


def test_hosted_merge_validation_rejects_semantic_base_drift_and_recovers(tmp_path: Path) -> None:
    """Prove head-only success cannot hide a semantic failure in the default merge checkout."""
    root, runner = tmp_path / "checkout", tmp_path / "runner"
    root.mkdir()
    _repository(root)
    (root / "runtime.py").write_text("VALUE = 1\n")
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "fixture runtime")
    _git(root, "checkout", "-b", "fixture-base")
    _git(root, "checkout", "-b", "fixture-head")
    test = root / "test_runtime.py"
    test.write_text("from runtime import VALUE\ndef test_value():\n    assert VALUE == 1\n")
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "fixture head")
    head = _git(root, "rev-parse", "HEAD")
    command = [sys.executable, "-m", "pytest", "-q", "test_runtime.py"]
    assert subprocess.run(command, cwd=root, capture_output=True, check=False).returncode == 0
    _git(root, "checkout", "fixture-base")
    (root / "runtime.py").write_text("VALUE = 22\n")
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "fixture advanced base")
    base = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/main", base)
    _git(root, "-c", "commit.gpgsign=false", "merge", "--no-edit", "fixture-head")
    merge = _git(root, "rev-parse", "HEAD")
    classified = _hosted_classification(root, runner, base, head)
    assert classified.returncode == 0 and classified.stdout.strip() == "full", classified.stderr
    assert _git(root, "rev-parse", "HEAD") == merge
    assert sum(line.startswith("worktree ") for line in _git(root, "worktree", "list", "--porcelain").splitlines()) == 1
    assert subprocess.run(command, cwd=root, capture_output=True, check=False).returncode == 1
    test.write_text("from runtime import VALUE\ndef test_value():\n    assert VALUE == 22\n")
    assert subprocess.run(command, cwd=root, capture_output=True, check=False).returncode == 0


def test_hosted_head_classification_keeps_docs_route_and_blocks_wrong_identity(tmp_path: Path) -> None:
    """Keep eligible head prose reduced while unknown identity blocks without moving validation HEAD."""
    root = tmp_path / "checkout"
    root.mkdir()
    base = _repository(root)
    (root / "README.md").write_text("# Updated prose\n")
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "fixture prose")
    head = _git(root, "rev-parse", "HEAD")
    accepted = _hosted_classification(root, tmp_path / "accepted", base, head)
    assert accepted.returncode == 0 and accepted.stdout.strip() == "docs", accepted.stderr
    blocked = _hosted_classification(root, tmp_path / "blocked", base, "missing-head")
    assert blocked.returncode != 0 and not blocked.stdout.strip()
    recovered = _hosted_classification(root, tmp_path / "recovered", base, head)
    assert recovered.returncode == 0 and recovered.stdout.strip() == "docs", recovered.stderr
    assert _git(root, "rev-parse", "HEAD") == head


def test_docs_wrapper_runs_real_quality_rejects_source_and_recovers(tmp_path: Path) -> None:
    """Exercise the real reduced route in a disposable copy, not the caller repo."""
    paths = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        env=_fixture_environment(),
        capture_output=True,
        check=True,
    ).stdout
    for raw in paths.split(b"\0"):
        if raw:
            relative = Path(raw.decode())
            destination = tmp_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
    base = _repository(tmp_path)
    shutil.copyfile(ROOT / "README.md", tmp_path / "README.md")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-m", "fixture tooling")
    base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", base)
    environment = {
        **_fixture_environment(),
        "UV_OFFLINE": "1",
        "MISE_CEILING_PATHS": str(tmp_path.parent),
        "MISE_TRUSTED_CONFIG_PATHS": str(tmp_path / ".mise.toml"),
    }
    environment.pop("UV_PROJECT_ENVIRONMENT", None)
    prepared = subprocess.run(
        ["mise", "exec", "--", "uv", "sync", "--frozen"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    prose = tmp_path / "README.md"
    prose.write_text(prose.read_text() + "\nDocumentation fixture clarification.\n")
    command = ["bash", "scripts/validate-docs.sh", "--base", base, "--head", base]
    for executable in (False, True, False):
        source = tmp_path / "fixture_runtime.py"
        if executable:
            source.write_text("value = 1\n")
        elif source.exists():
            source.unlink()
        result = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
        assert result.returncode == (2 if executable else 0), result.stdout + result.stderr
        assert "validation: start tests" not in result.stdout and "validation: start installed" not in result.stdout
        if not executable:
            assert "validation: finish codestyle status=0" in result.stdout
            assert "validation: finish docs-tests status=0" in result.stdout
    valid_prose = prose.read_text()
    prose.write_text(valid_prose.replace("From the checkout root:", "At the checkout root:"))
    broken = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
    assert broken.returncode != 0, "documentation route concealed a failed README contract"
    assert "validation: finish docs-tests status=1" in broken.stdout
    assert "validation: start diff" not in broken.stdout
    prose.write_text(valid_prose)
    recovered = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
