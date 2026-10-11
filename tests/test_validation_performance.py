"""Exact docs classification, fail-closed phases and worker isolation proof."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validation_scope import git_environment, validation_scope

ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *arguments: str) -> str:
    environment = git_environment()
    return subprocess.run(
        ["git", *arguments], cwd=root, env=environment, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repository(root: Path) -> str:
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
    base = _repository(tmp_path)
    source = tmp_path / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("changed\n")
    assert validation_scope(tmp_path, base, base) == "full"


def test_empty_stale_head_symlink_and_mode_changes_do_not_select_docs(tmp_path: Path) -> None:
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
    base = _repository(tmp_path)
    (tmp_path / "README.md").write_text("changed\n")
    with pytest.raises(subprocess.CalledProcessError):
        validation_scope(tmp_path, "missing-reference", base)
    assert validation_scope(tmp_path, base, base) == "docs"


def test_unaccepted_base_and_staged_mode_cannot_hide_executable_changes(tmp_path: Path) -> None:
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


def test_base_advanced_after_branch_creation_falls_back_to_full(tmp_path: Path) -> None:
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
    assert validation_scope(tmp_path, advanced, head) == "full"


def test_inherited_git_selectors_do_not_mutate_or_classify_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    result = subprocess.run(
        ["bash", "scripts/validate-repository.sh", argument], cwd=ROOT, capture_output=True, check=False
    )
    assert result.returncode == 2


def test_parallel_workers_preserve_isolation_and_propagate_failure(tmp_path: Path) -> None:
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
    workflow = (ROOT / ".github/workflows/validate.yml").read_text()
    assert "cp trusted-base/scripts/validation_scope.py" in workflow
    assert "scope=full" in workflow
    assert "github.event_name != 'pull_request' || steps.pr_contract.outputs.scope != 'docs'" in workflow
    for phase in ("quality", "tests", "build", "installed", "diff"):
        assert f"bash scripts/validate-repository.sh {phase}" in workflow
    assert "github.event_name == 'pull_request' && steps.pr_contract.outputs.scope == 'docs'" in workflow
    assert "bash scripts/validate-repository.sh docs-tests" in workflow
    wrapper = (ROOT / "scripts/validate-repository.sh").read_text()
    assert 'phase="${1:-all}"' in wrapper and "pytest -n 2 --dist load --durations=25" in wrapper
    assert "tests/test_public_repository_boundary.py tests/test_skill_validation_architecture.py" in wrapper


def test_docs_wrapper_runs_real_quality_rejects_source_and_recovers(tmp_path: Path) -> None:
    """Exercise the real reduced route in a disposable copy, not the caller repo."""
    paths = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        env=git_environment(),
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
        **git_environment(),
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
