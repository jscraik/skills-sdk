"""Race, resource, and object-store boundaries for private Git status snapshots."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from skills_sdk.validation import pr_sweep as pr_sweep_validation


def _fixture_git_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=_fixture_git_environment())


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / ".gitignore").write_text("", encoding="utf-8")
    _git(repo, "add", ".gitignore")
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


def test_snapshot_blocks_changed_ignored_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    (repo / ".gitignore").write_text("dirty.txt\n", encoding="utf-8")
    original_copy_tree = pr_sweep_validation.copy_snapshot_tree

    def restore_ignore_before_copy(src: Path, dst: Path, *args: object, **kwargs: object) -> None:
        if Path(src) == repo:
            (repo / ".gitignore").write_text("", encoding="utf-8")
        original_copy_tree(src, dst, *args, **kwargs)
        if Path(src) == repo:
            (repo / ".gitignore").write_text("dirty.txt\n", encoding="utf-8")

    monkeypatch.setattr(pr_sweep_validation, "copy_snapshot_tree", restore_ignore_before_copy)
    result = pr_sweep_validation.validate_pr_sweep_dirty_closeout(repo, require_clean=True)
    assert result.status == "blocked"
    assert result.findings[0].code == "git_status_unavailable"


def test_snapshot_blocks_ignore_rule_added_only_during_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    original_copy_tree = pr_sweep_validation.copy_snapshot_tree

    def add_ignore_during_copy(src: Path, dst: Path, *args: object, **kwargs: object) -> None:
        if Path(src) == repo:
            (repo / ".gitignore").write_text("dirty.txt\n", encoding="utf-8")
        original_copy_tree(src, dst, *args, **kwargs)
        if Path(src) == repo:
            (repo / ".gitignore").write_text("", encoding="utf-8")

    monkeypatch.setattr(pr_sweep_validation, "copy_snapshot_tree", add_ignore_during_copy)
    result = pr_sweep_validation.validate_pr_sweep_dirty_closeout(repo, require_clean=True)
    assert result.status == "blocked"
    assert result.findings[0].code == "git_status_unavailable"


@pytest.mark.parametrize("entry_kind", ["file", "directory", "symlink"])
def test_snapshot_object_budget_counts_empty_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_kind: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for index in range(3):
        entry = source / f"entry-{index}"
        if entry_kind == "file":
            entry.touch()
        elif entry_kind == "directory":
            entry.mkdir()
        else:
            entry.symlink_to("missing")
    destination = tmp_path / "destination"
    monkeypatch.setattr(pr_sweep_validation, "_MAX_SNAPSHOT_ENTRIES", 2)
    budget = pr_sweep_validation.SnapshotBudget(
        pr_sweep_validation._MAX_SNAPSHOT_BYTES,
        pr_sweep_validation._MAX_SNAPSHOT_ENTRIES,
        pr_sweep_validation._MAX_SNAPSHOT_DEPTH,
    )

    with pytest.raises(OSError, match="object budget"):
        pr_sweep_validation.copy_snapshot_tree(source, destination, budget)

    assert len(list(destination.iterdir())) == 1


def test_snapshot_object_budget_rejects_excessive_depth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    (source / "first" / "second").mkdir(parents=True)
    destination = tmp_path / "destination"
    monkeypatch.setattr(pr_sweep_validation, "_MAX_SNAPSHOT_DEPTH", 1)
    budget = pr_sweep_validation.SnapshotBudget(
        pr_sweep_validation._MAX_SNAPSHOT_BYTES,
        pr_sweep_validation._MAX_SNAPSHOT_ENTRIES,
        pr_sweep_validation._MAX_SNAPSHOT_DEPTH,
    )

    with pytest.raises(OSError, match="object budget"):
        pr_sweep_validation.copy_snapshot_tree(source, destination, budget)

    assert (destination / "first").is_dir()
    assert not (destination / "first" / "second").exists()


@pytest.mark.parametrize("limit", ["bytes", "records"])
def test_git_output_budget_blocks_unbounded_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    repo = _repo(tmp_path)
    if limit == "bytes":
        monkeypatch.setattr(pr_sweep_validation, "_MAX_GIT_OUTPUT_BYTES", 1)
    else:
        (repo / "second.txt").touch()
        _git(repo, "add", "second.txt")
        monkeypatch.setattr(pr_sweep_validation, "_MAX_GIT_OUTPUT_RECORDS", 1)

    result = pr_sweep_validation.validate_pr_sweep_dirty_closeout(repo, require_clean=True)

    assert result.status == "blocked"
    assert result.findings[0].code == "git_status_unavailable"


def test_snapshot_matches_source_status_for_untracked_fifo(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO support is unavailable on this host")
    repo = _repo(tmp_path)
    os.mkfifo(repo / "untracked-fifo")
    source_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        env=_fixture_git_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    assert source_status.stdout == ""
    result = pr_sweep_validation.validate_pr_sweep_dirty_closeout(repo, require_clean=True)
    assert result.status == "pass"


def test_snapshot_blocks_system_attributes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    attributes = tmp_path / "system-attributes"
    attributes.write_text("* text\n", encoding="utf-8")
    original_run_git = pr_sweep_validation._run_git

    def system_attributes_path(root: Path, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args == ("var", "GIT_ATTR_SYSTEM"):
            return subprocess.CompletedProcess(args, 0, str(attributes) + "\n", "")
        return original_run_git(root, *args, **kwargs)

    monkeypatch.setattr(pr_sweep_validation, "_run_git", system_attributes_path)
    result = pr_sweep_validation.validate_pr_sweep_dirty_closeout(repo, require_clean=True)
    assert result.status == "blocked"
    assert result.findings[0].code == "ambient_git_config"


def test_snapshot_blocks_external_object_alternates(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    external = tmp_path / "external-objects"
    external.mkdir()
    (repo / ".git" / "objects" / "info" / "alternates").write_text(str(external) + "\n", encoding="utf-8")
    result = pr_sweep_validation.validate_pr_sweep_dirty_closeout(repo, require_clean=True)
    assert result.status == "blocked"
    assert result.findings[0].code == "git_status_unavailable"


def test_snapshot_blocks_symlinked_object_alternates_before_open(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO support is unavailable on this host")
    repo = _repo(tmp_path)
    external = tmp_path / "alternate-fifo"
    os.mkfifo(external)
    (repo / ".git" / "objects" / "info" / "alternates").symlink_to(external)
    result = pr_sweep_validation.validate_pr_sweep_dirty_closeout(repo, require_clean=True)
    assert result.status == "blocked"
    assert result.findings[0].code == "git_status_unavailable"


def test_snapshot_inspects_contained_metadata_symlink_targets(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    objects = repo / ".git" / "objects"
    contained = repo / ".git" / "private-objects"
    objects.rename(contained)
    objects.symlink_to("private-objects", target_is_directory=True)
    external = tmp_path / "external-object"
    external.write_text("outside\n", encoding="utf-8")
    (contained / "unreferenced-object").symlink_to(external)
    result = pr_sweep_validation.validate_pr_sweep_dirty_closeout(repo, require_clean=True)
    assert result.status == "blocked"
    assert result.findings[0].code == "git_status_unavailable"


def test_snapshot_accepts_contained_metadata_symlink_targets(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    objects = repo / ".git" / "objects"
    contained = repo / ".git" / "private-objects"
    objects.rename(contained)
    objects.symlink_to("private-objects", target_is_directory=True)
    (contained / "unreferenced-object").symlink_to("../HEAD")
    result = pr_sweep_validation.validate_pr_sweep_dirty_closeout(repo, require_clean=True)
    assert result.status == "pass"
