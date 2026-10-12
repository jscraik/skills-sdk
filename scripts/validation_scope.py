"""Select documentation proof only for exact, ordinary tracked prose changes."""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
from pathlib import Path

_ROOT_PROSE = {"README.md", "ARCHITECTURE.md", "UBIQUITOUS.md", "CHANGELOG.md", "SUPPORT.md"}
_SUFFIXES = {".md", ".mdx", ".adoc", ".rst"}


def git_environment() -> dict[str, str]:
    """Keep inherited Git selectors and configuration out of checkout queries."""
    return {
        **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }


def _git(root: Path, *arguments: str) -> bytes:
    """Run a Git query in the checkout with inherited Git settings removed."""
    return subprocess.run(
        ["git", "-c", "core.fileMode=true", "-c", "diff.autoRefreshIndex=false", *arguments],
        cwd=root,
        env=git_environment(),
        check=True,
        capture_output=True,
    ).stdout


def _paths(output: bytes) -> set[str]:
    """Decode nonempty paths from NUL-delimited Git output into a set."""
    return {path.decode("utf-8") for path in output.split(b"\0") if path}


def _ordinary_prose(root: Path, path: str, revisions: tuple[str, str]) -> bool:
    """Check the prose allowlist and reject unsafe revision, index, or filesystem modes."""
    relative = Path(path)
    if relative.name == "AGENTS.md" or path == "docs/standards.md":
        return False
    if path not in _ROOT_PROSE and not (relative.parts[0] == "docs" and relative.suffix in _SUFFIXES):
        return False
    for revision in revisions:
        entry = _git(root, "ls-tree", "-z", revision, "--", path)
        if entry and not entry.startswith(b"100644 blob "):
            return False
    indexed = _git(root, "ls-files", "--stage", "-z", "--", path)
    for entry in indexed.split(b"\0"):
        if entry and (not entry.startswith(b"100644 ") or not entry.partition(b"\t")[0].endswith(b" 0")):
            return False
    source = root / path
    if any(parent.is_symlink() for parent in (source, *source.parents) if parent != root):
        return False
    return not source.exists() or (source.is_file() and not source.stat().st_mode & 0o111)


def _tracked_executable_drift(root: Path) -> bool:
    """Detect any execute bit on tracked non-executable files, including bits Git ignores."""
    for entry in _git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, _, path = entry.partition(b"\t")
        if metadata.split()[0] != b"100644":
            continue
        try:
            mode = (root / path.decode("utf-8")).lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISREG(mode) and mode & 0o111:
            return True
    return False


def validation_scope(root: Path, base: str, head: str) -> str:
    """Fail closed on unknown identity, non-prose bytes, modes and dirty paths."""
    if Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root.resolve():
        raise ValueError("root must identify the checkout top level")
    actual = _git(root, "rev-parse", "HEAD").decode().strip()
    resolved = _git(root, "rev-parse", "--verify", f"{head}^{{commit}}").decode().strip()
    baseline = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
    if actual != resolved:
        raise ValueError("head must identify the current checkout")
    accepted = _git(root, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}").decode().strip()
    # An unmerged head cannot be declared as its own accepted base to hide code.
    _git(root, "merge-base", "--is-ancestor", baseline, accepted)
    try:
        _git(root, "merge-base", "--is-ancestor", accepted, resolved)
    except subprocess.CalledProcessError as error:
        if error.returncode != 1:
            raise
        return "full"
    # Index flags can hide modified tracked files from every diff query.
    indexed = _git(root, "ls-files", "-v", "-z")
    if any(entry and not entry.startswith(b"H ") for entry in indexed.split(b"\0")) or _tracked_executable_drift(root):
        return "full"
    paths = _paths(_git(root, "diff", "--no-renames", "--name-only", "-z", baseline, resolved, "--"))
    paths |= _paths(_git(root, "diff", "--cached", "--no-renames", "--name-only", "-z", "HEAD", "--"))
    worktree = _git(root, "status", "--porcelain=v1", "--untracked-files=no", "--no-renames", "-z")
    paths |= {entry[3:].decode("utf-8") for entry in worktree.split(b"\0") if entry}
    paths |= _paths(_git(root, "ls-files", "--others", "--exclude-standard", "-z"))
    if not paths or not all(_ordinary_prose(root, path, (baseline, resolved)) for path in paths):
        return "full"
    return "docs"


def main() -> int:
    """Print the validation scope, exiting with status 2 when identity checks fail."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    try:
        print(validation_scope(Path.cwd(), args.base, args.head))
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, ValueError) as error:
        parser.exit(2, f"validation scope blocked: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
