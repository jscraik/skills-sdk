"""Private snapshot submodule and content-hashing regressions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from skills_sdk.validation import validate_pr_sweep_dirty_closeout

_GIT_LOCATION_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_PREFIX",
    }
)


def _git_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, env=_git_environment(), check=True, capture_output=True, text=True)


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


@pytest.mark.parametrize("variable", sorted(_GIT_LOCATION_VARIABLES))
def test_fixture_git_ignores_repository_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, str(tmp_path / "unrelated"))
    monkeypatch.setenv("SDK_FIXTURE_MARKER", "preserved")
    assert _git_environment()["SDK_FIXTURE_MARKER"] == "preserved"
    assert variable not in _git_environment()
    repo = _repo(tmp_path)
    assert (repo / ".git" / "index").is_file()


def test_fixture_git_calls_preserve_inherited_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    caller = _repo(tmp_path)
    index_before = (caller / ".git" / "index").read_bytes()
    head_before = (caller / ".git" / "HEAD").read_bytes()
    monkeypatch.setenv("GIT_DIR", str(caller / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(caller))
    monkeypatch.setenv("GIT_INDEX_FILE", str(caller / ".git" / "index"))
    fixture_parent = tmp_path / "fixture"
    fixture_parent.mkdir()
    fixture = _repo(fixture_parent)

    assert (fixture / ".git" / "index").is_file()
    assert (caller / ".git" / "index").read_bytes() == index_before
    assert (caller / ".git" / "HEAD").read_bytes() == head_before


def test_dirty_closeout_sees_submodule_even_when_repo_ignores_it(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    parent = tmp_path / "parent"
    parent.mkdir()
    _git(parent, "init")
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", str(source), "module"],
        cwd=parent,
        env=_git_environment(),
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
    if hasattr(os, "mkfifo"):
        tracked = parent / "module" / "tracked.txt"
        tracked.unlink()
        os.mkfifo(tracked)
        blocked = validate_pr_sweep_dirty_closeout(parent, require_clean=True)
        assert blocked.status == "blocked"
        assert blocked.findings[0].code == "git_status_unavailable"


def test_dirty_closeout_blocks_submodule_clean_filter(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    parent = tmp_path / "parent-filter"
    parent.mkdir()
    _git(parent, "init")
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", str(source), "module"],
        cwd=parent,
        env=_git_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    sentinel = tmp_path / "submodule-filter-ran"
    _git(parent / "module", "config", "filter.evil.clean", f"touch {sentinel}")
    (parent / "module" / ".gitattributes").write_text("tracked.txt filter=evil\n", encoding="utf-8")
    (parent / "module" / "tracked.txt").write_text("changed\n", encoding="utf-8")
    result = validate_pr_sweep_dirty_closeout(parent, require_clean=True)
    assert result.status == "blocked"
    assert result.findings[0].code == "clean_filter_present"
    assert not sentinel.exists()


@pytest.mark.parametrize("config_key", ["core.attributesFile", "include.path"])
def test_dirty_closeout_blocks_submodule_external_configuration(tmp_path: Path, config_key: str) -> None:
    source = _repo(tmp_path)
    parent = tmp_path / "parent-external-config"
    parent.mkdir()
    _git(parent, "init")
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", str(source), "module"],
        cwd=parent,
        env=_git_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    sentinel = tmp_path / "external-filter-ran"
    external = tmp_path / "external-config"
    if config_key == "core.attributesFile":
        external.write_text("tracked.txt filter=evil\n", encoding="utf-8")
    else:
        external.write_text(f'[filter "evil"]\n clean = touch {sentinel}\n', encoding="utf-8")
    _git(parent / "module", "config", "filter.evil.clean", f"touch {sentinel}")
    _git(parent / "module", "config", config_key, str(external))
    (parent / "module" / "tracked.txt").write_text("changed\n", encoding="utf-8")
    result = validate_pr_sweep_dirty_closeout(parent, require_clean=True)
    assert result.status == "blocked"
    assert result.findings[0].code == "git_config_include"
    assert not sentinel.exists()


@pytest.mark.parametrize("symlink", [False, True])
def test_dirty_closeout_checks_blobs_when_status_stat_cache_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symlink: bool
) -> None:
    from skills_sdk.validation import pr_sweep

    repo = _repo(tmp_path)
    tracked = repo / "tracked.txt"
    if symlink:
        tracked.unlink()
        tracked.symlink_to("initial")
        _git(repo, "add", "tracked.txt")
    original = tracked.lstat()
    index_before = (repo / ".git" / "index").read_bytes()
    if symlink:
        tracked.unlink()
        tracked.symlink_to("changed")
    else:
        tracked.write_text("changed\n", encoding="utf-8")
    os.utime(tracked, ns=(original.st_atime_ns, original.st_mtime_ns), follow_symlinks=False)
    run_git = pr_sweep._run_git

    def matching_stat_status(
        root: Path, *args: str, input_text: str | None = None, force_worktree: bool = False
    ) -> subprocess.CompletedProcess[str]:
        if args[0] == "status":
            # Model a filesystem whose cached stat tuple, including ctime, matches.
            return subprocess.CompletedProcess(args, 0, "", "")
        return run_git(root, *args, input_text=input_text, force_worktree=force_worktree)

    monkeypatch.setattr(pr_sweep, "_run_git", matching_stat_status)
    result = validate_pr_sweep_dirty_closeout(repo, require_clean=True)
    assert result.status == "fail"
    assert result.dirty_state is not None
    assert result.dirty_state.unstaged_paths == ("tracked.txt",)
    assert (repo / ".git" / "index").read_bytes() == index_before


def test_dirty_closeout_hashes_staging_conversions_against_index(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / ".gitattributes").write_text("*.txt text eol=crlf\n", encoding="utf-8")
    tracked = repo / "tracked.txt"
    tracked.write_bytes(b"staged\r\n")
    _git(repo, "add", ".")
    index_before = (repo / ".git" / "index").read_bytes()
    result = validate_pr_sweep_dirty_closeout(repo)
    assert result.status == "fail"  # Staged changes still need a ledger.
    assert result.dirty_state is not None
    assert result.dirty_state.unstaged_paths == ()
    assert (repo / ".git" / "index").read_bytes() == index_before


def test_dirty_closeout_reports_nested_file_when_parent_becomes_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    nested = repo / "nested"
    nested.mkdir()
    (nested / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git(repo, "add", "nested/tracked.txt")
    nested.joinpath("tracked.txt").unlink()
    nested.rmdir()
    nested.write_text("replacement\n", encoding="utf-8")

    result = validate_pr_sweep_dirty_closeout(repo, require_clean=True)

    assert result.status == "fail"
    assert result.dirty_state is not None
    assert "nested/tracked.txt" in result.dirty_state.dirty_paths


def test_content_scan_records_a_tracked_file_deleted_after_status(tmp_path: Path) -> None:
    from skills_sdk.validation import pr_sweep

    repo = _repo(tmp_path)
    (repo / "tracked.txt").unlink()
    assert pr_sweep._content_dirty_paths(repo) == {"tracked.txt"}


def test_dirty_closeout_accepts_unchanged_crlf_index_blob_after_autocrlf_change(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "tracked.txt").write_bytes(b"original\r\n")
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
        "crlf baseline",
    )
    _git(repo, "config", "core.autocrlf", "input")

    result = validate_pr_sweep_dirty_closeout(repo, require_clean=True)

    assert result.status == "pass"


def test_batched_hashing_preserves_a_leading_quote_and_does_not_run_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skills_sdk.validation import pr_sweep

    repo = _repo(tmp_path)
    sentinel = tmp_path / "filter-ran"
    _git(repo, "config", "filter.evil.clean", f"touch {sentinel}")
    (repo / ".gitattributes").write_text("payload filter=evil\n", encoding="utf-8")
    (repo / ".gitignore").write_text("payload\n", encoding="utf-8")
    (repo / "payload").write_text("ignored\n", encoding="utf-8")
    quoted = repo / '"payload"'
    quoted.write_text("start\n", encoding="utf-8")
    _git(repo, "add", '"payload"')
    original = quoted.stat()
    quoted.write_text("other\n", encoding="utf-8")
    os.utime(quoted, ns=(original.st_atime_ns, original.st_mtime_ns))
    run_git = pr_sweep._run_git

    def cached_status(
        root: Path, *args: str, input_text: str | None = None, force_worktree: bool = False
    ) -> subprocess.CompletedProcess[str]:
        if args[0] == "status":
            return subprocess.CompletedProcess(args, 0, "", "")
        return run_git(root, *args, input_text=input_text, force_worktree=force_worktree)

    monkeypatch.setattr(pr_sweep, "_run_git", cached_status)
    result = validate_pr_sweep_dirty_closeout(repo, require_clean=True)
    assert result.status == "fail"
    assert result.dirty_state is not None
    assert result.dirty_state.unstaged_paths == ('"payload"',)
    assert not sentinel.exists()
