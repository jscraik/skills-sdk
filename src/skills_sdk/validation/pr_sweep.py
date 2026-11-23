"""Portable read-only checks for recurring PR findings and dirty closeout."""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.pr_sweep import PrSweepDirtyState, PrSweepFinding, PrSweepValidationResult
from skills_sdk.validation._pr_sweep_snapshot import SnapshotBudget, copy_snapshot_tree

_GIT_INSPECTION_CONFIG = (
    "core.checkStat=default",
    "core.fileMode=true",
    "core.fsmonitor=false",
    "core.ignoreStat=false",
    "core.trustCtime=true",
    "core.untrackedCache=false",
)
_MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024
_MAX_SNAPSHOT_ENTRIES = 100_000
_MAX_SNAPSHOT_DEPTH = 64
_MAX_GIT_INPUT_BYTES = 8 * 1024 * 1024
_MAX_GIT_OUTPUT_BYTES = 4 * 1024 * 1024
_MAX_GIT_OUTPUT_RECORDS = 300_000
_GIT_TIMEOUT_SECONDS = 30


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


def _git_environment(*, isolated: bool = False) -> dict[str, str]:
    discovery_keys = {"GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM"}
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_") or key in discovery_keys
    }
    environment["LC_ALL"] = "C"
    if isolated:
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_ATTR_NOSYSTEM="1")
    return environment


def _run_git(
    repo_root: Path, *args: str, input_text: str | None = None, force_worktree: bool = False
) -> subprocess.CompletedProcess[str]:
    config_args = [argument for setting in _GIT_INSPECTION_CONFIG for argument in ("-c", setting)]
    command = [
        "git",
        *config_args,
        *([f"--work-tree={repo_root}"] if force_worktree else []),
        "--no-optional-locks",
        *args,
    ]
    payload = input_text.encode("utf-8") if input_text is not None else b""
    if len(payload) > _MAX_GIT_INPUT_BYTES:
        raise OSError("Git input exceeds its inspection budget")
    separator = b"\0" if "-z" in args or "--null" in args else b"\n"
    with TemporaryFile() as input_file:
        input_file.write(payload)
        input_file.seek(0)
        with subprocess.Popen(
            command,
            cwd=repo_root,
            env=_git_environment(isolated=force_worktree),
            stdin=input_file if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as process:
            stdout, stderr = _read_git_output(process, separator)
    return subprocess.CompletedProcess(command, process.returncode, stdout.decode("utf-8"), stderr.decode("utf-8"))


def _read_git_output(process: subprocess.Popen[bytes], separator: bytes) -> tuple[bytes, bytes]:
    if process.stdout is None or process.stderr is None:
        raise OSError("Git output pipes are unavailable")
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    records = 0
    deadline = time.monotonic() + _GIT_TIMEOUT_SECONDS
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, _GIT_TIMEOUT_SECONDS)
            events = selector.select(remaining)
            if not events:
                raise subprocess.TimeoutExpired(process.args, _GIT_TIMEOUT_SECONDS)
            for key, _ in events:
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if sum(map(len, chunks.values())) + len(chunk) > _MAX_GIT_OUTPUT_BYTES:
                    raise OSError("Git output exceeds its inspection budget")
                chunks[key.data].extend(chunk)
                if key.data == "stdout":
                    records += chunk.count(separator)
                    if records > _MAX_GIT_OUTPUT_RECORDS:
                        raise OSError("Git output exceeds its record budget")
        process.wait(timeout=max(0, deadline - time.monotonic()))
        if chunks["stdout"] and not chunks["stdout"].endswith(separator):
            records += 1
        if records > _MAX_GIT_OUTPUT_RECORDS:
            raise OSError("Git output exceeds its record budget")
        return bytes(chunks["stdout"]), bytes(chunks["stderr"])
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def _resolved_git_path(repo_root: Path, *args: str, force_worktree: bool = False) -> Path:
    completed = _run_git(repo_root, *args, force_worktree=force_worktree)
    if completed.returncode != 0 or not completed.stdout.strip():
        raise OSError("could not resolve Git metadata")
    return Path(completed.stdout.strip()).resolve()


def _materialize_git_metadata(repo_root: Path, snapshot_root: Path, private_root: Path, budget: SnapshotBudget) -> None:
    marker = snapshot_root / ".git"
    if marker.is_dir() and not marker.is_symlink():
        return
    git_directory = _resolved_git_path(repo_root, "rev-parse", "--path-format=absolute", "--git-dir")
    common_directory = _resolved_git_path(repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if marker.exists() or marker.is_symlink():
        marker.unlink()
    copy_snapshot_tree(git_directory, marker, budget)
    if common_directory == git_directory:
        return
    common_snapshot = private_root / "common-git-dir"
    copy_snapshot_tree(common_directory, common_snapshot, budget)
    copied_commondir = marker / "commondir"
    if copied_commondir.is_symlink():
        copied_commondir.unlink()
    copied_commondir.write_text(os.path.relpath(common_snapshot, marker) + "\n", encoding="utf-8")
    source_modules = common_snapshot / "modules"
    if source_modules.is_dir() and not (marker / "modules").exists():
        copy_snapshot_tree(source_modules, marker / "modules", budget)


def _snapshot_worktree(repo_root: Path, private_root: Path) -> Path:
    repo_root = repo_root.resolve()
    if private_root.resolve().is_relative_to(repo_root.resolve()):
        raise OSError("private inspection directory is inside the supplied worktree")
    ignored_result = _run_git(repo_root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    tracked_result = _run_git(repo_root, "ls-files", "--cached", "-z")
    if (
        ignored_result.returncode != 0
        or tracked_result.returncode != 0
        or len(ignored_result.stdout) > 4 * 1024 * 1024
        or len(tracked_result.stdout) > 4 * 1024 * 1024
    ):
        raise OSError("could not enumerate ignored snapshot paths")
    ignored = {path for path in ignored_result.stdout.split("\0") if path}
    tracked = {path for path in tracked_result.stdout.split("\0") if path}

    def skip_ignored(relative: Path, mode: int) -> bool:
        path = relative.as_posix()
        if not stat.S_ISDIR(mode) and relative.name not in {".gitattributes", ".gitignore"} and path in ignored:
            return True
        if path in tracked or relative.name == ".git" or not (stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)):
            return False
        return not any((repo_root / parent / ".git").exists() for parent in relative.parents if parent != Path("."))

    snapshot_root = private_root / "worktree"
    budget = SnapshotBudget(_MAX_SNAPSHOT_BYTES, _MAX_SNAPSHOT_ENTRIES, _MAX_SNAPSHOT_DEPTH)
    copy_snapshot_tree(repo_root, snapshot_root, budget, should_skip=skip_ignored)
    _materialize_git_metadata(repo_root, snapshot_root, private_root, budget)
    snapshot_ignored = _run_git(
        snapshot_root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z", force_worktree=True
    )
    if (
        snapshot_ignored.returncode != 0
        or len(snapshot_ignored.stdout) > 4 * 1024 * 1024
        or not set(filter(None, snapshot_ignored.stdout.split("\0"))).issubset(ignored)
    ):
        raise OSError("ignored paths differ in the private snapshot")
    if ignored:
        checked = _run_git(
            snapshot_root,
            "check-ignore",
            "--stdin",
            "-z",
            input_text="\0".join(sorted(ignored)) + "\0",
            force_worktree=True,
        )
        if checked.returncode != 0 or set(filter(None, checked.stdout.split("\0"))) != ignored:
            raise OSError("ignored paths are not ignored by the private snapshot")
    current_ignored = _run_git(repo_root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    if (
        current_ignored.returncode != 0
        or len(current_ignored.stdout) > 4 * 1024 * 1024
        or set(filter(None, current_ignored.stdout.split("\0"))) != ignored
    ):
        raise OSError("ignored paths changed during private snapshot creation")
    return snapshot_root


def _git_metadata_is_private(repo_root: Path, private_root: Path) -> bool:
    private_root = private_root.resolve()
    metadata_roots: list[Path] = []
    for argument in ("--git-dir", "--git-common-dir"):
        try:
            metadata_root = _resolved_git_path(
                repo_root,
                "rev-parse",
                "--path-format=absolute",
                argument,
                force_worktree=True,
            )
            metadata_root.relative_to(private_root)
        except (OSError, ValueError):
            return False
        metadata_roots.append(metadata_root)
    for name in ("index", "config", "config.worktree", "objects", "info/attributes", "info/exclude"):
        try:
            _resolved_git_path(
                repo_root,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                name,
                force_worktree=True,
            ).relative_to(private_root)
        except (OSError, ValueError):
            return False
    for path in metadata_roots[0].glob("sharedindex.*"):
        try:
            path.resolve().relative_to(private_root)
        except (OSError, RuntimeError, ValueError):
            return False
    for metadata_root in metadata_roots:
        alternates = metadata_root / "objects" / "info" / "alternates"
        if alternates.exists() or alternates.is_symlink():
            return False

    def reject_walk_error(error: OSError) -> None:
        raise error

    try:
        inspected_directories: set[Path] = set()
        for metadata_root in metadata_roots:
            for directory, names, files in os.walk(metadata_root, followlinks=True, onerror=reject_walk_error):
                resolved_directory = Path(directory).resolve()
                if not resolved_directory.is_relative_to(private_root):
                    return False
                if resolved_directory in inspected_directories:
                    names.clear()
                    continue
                inspected_directories.add(resolved_directory)
                for name in names + files:
                    entry = Path(directory) / name
                    if entry.is_symlink() and not entry.resolve().is_relative_to(private_root):
                        return False
    except (OSError, RuntimeError):
        return False
    return True


def _git_config_has_includes(repo_root: Path) -> bool | None:
    worktree_config = _resolved_git_path(
        repo_root, "rev-parse", "--path-format=absolute", "--git-path", "config.worktree", force_worktree=True
    )
    sources = [("--local",)]
    if worktree_config.exists():
        sources.append(("--file", str(worktree_config)))
    for source in sources:
        completed = _run_git(repo_root, "config", *source, "--no-includes", "--null", "--list", force_worktree=True)
        if completed.returncode != 0:
            return None
        keys = (entry.partition("\n")[0].casefold() for entry in completed.stdout.split("\0") if entry)
        if any(
            key in {"include.path", "core.attributesfile", "core.excludesfile"}
            or (key.startswith("includeif.") and key.endswith(".path"))
            for key in keys
        ):
            return True
    return False


def _ambient_status_config_is_supported(repo_root: Path) -> bool:
    relevant = {
        "core.autocrlf",
        "core.eol",
        "core.safecrlf",
        "core.excludesfile",
        "core.attributesfile",
        "core.symlinks",
        "core.filemode",
        "core.ignorecase",
    }
    xdg_root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if any((xdg_root / "git" / name).exists() for name in ("ignore", "attributes")):
        return False
    system_attributes = _run_git(repo_root, "var", "GIT_ATTR_SYSTEM")
    if system_attributes.returncode != 0 or not system_attributes.stdout.strip():
        return False
    if Path(system_attributes.stdout.strip()).exists():
        return False
    config_sources = (
        ("--file", str(Path.home() / ".gitconfig")),
        ("--file", str(xdg_root / "git" / "config")),
        ("--system",),
    )
    for scope in config_sources:
        if scope[0] == "--file" and not Path(scope[1]).exists():
            continue
        configured = _run_git(repo_root, "config", *scope, "--name-only", "--list")
        if configured.returncode != 0 and "No such file or directory" in configured.stderr:
            continue
        if configured.returncode not in {0, 1}:
            return False
        keys = {key.casefold() for key in configured.stdout.splitlines()}
        if (
            keys & relevant
            or "include.path" in keys
            or any(key.startswith("includeif.") and key.endswith(".path") for key in keys)
        ):
            return False
    return True


def _git_status_preflight(
    repo_root: Path, *, private_root: Path | None = None, depth: int = 0
) -> tuple[str | None, str | None]:
    """Reject index or attributes that can hide dirt or execute a clean filter."""
    if depth > 8:
        return "git_status_unavailable", "submodule nesting exceeds safe inspection depth"
    if private_root is not None:
        if not _git_metadata_is_private(repo_root, private_root):
            return "git_status_unavailable", "Git metadata escapes the private snapshot"
        if _git_config_has_includes(repo_root) is not False:
            return "git_config_include", "Git configuration references paths outside the private snapshot"
    for key in ("core.fileMode", "core.symlinks"):
        configured = _run_git(
            repo_root, "config", "--local", "--bool", "--get", key, force_worktree=private_root is not None
        )
        if configured.returncode not in {0, 1}:
            return "git_status_unavailable", "could not inspect local Git filesystem settings"
        if configured.stdout.strip() == "false":
            return "git_filesystem_mode_unsupported", "Git filesystem settings prevent trustworthy content inspection"
    tracked = _run_git(repo_root, "ls-files", "-v", "-z", force_worktree=private_root is not None)
    if tracked.returncode != 0:
        return "git_status_unavailable", "could not inspect tracked Git paths"
    records = [record for record in tracked.stdout.split("\0") if record]
    if any(len(record) < 3 or record[1] != " " for record in records):
        return "git_status_unavailable", "could not parse tracked Git paths"
    if any(record[0].islower() or record[0] == "S" for record in records):
        return "index_visibility_flags", "index visibility flags prevent a trustworthy clean result"
    staged = _run_git(repo_root, "ls-files", "--stage", "-z", force_worktree=private_root is not None)
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
            worktree = _run_git(submodule_root, "config", "--get", "core.worktree", force_worktree=True)
            if worktree.returncode not in {0, 1}:
                return "git_status_unavailable", "could not inspect submodule worktree configuration"
            if worktree.returncode == 0:
                git_directory = _resolved_git_path(
                    submodule_root, "rev-parse", "--path-format=absolute", "--git-dir", force_worktree=True
                )
                if (git_directory / worktree.stdout.strip()).resolve() != submodule_root.resolve():
                    return "submodule_worktree_escape", "submodule status would inspect outside the private snapshot"
            blocker_code, blocker_message = _git_status_preflight(
                submodule_root, private_root=private_root, depth=depth + 1
            )
            if blocker_code is not None:
                return blocker_code, blocker_message
    paths = [record[2:] for record in records]
    if paths:
        attributes = _run_git(
            repo_root,
            "check-attr",
            "-z",
            "--stdin",
            "filter",
            input_text="\0".join(paths) + "\0",
            force_worktree=private_root is not None,
        )
        if attributes.returncode != 0:
            return "git_status_unavailable", "could not inspect tracked Git attributes"
        fields = attributes.stdout.split("\0")
        if fields[-1] != "" or (len(fields) - 1) % 3 != 0:
            return "git_status_unavailable", "could not parse tracked Git attributes"
        if any(value not in {"unspecified", "unset"} for value in fields[2:-1:3]):
            return "clean_filter_present", "tracked Git filter attributes prevent read-only status inspection"
    return None, None


def _content_dirty_paths(repo_root: Path) -> set[str]:
    """Compare index blobs independently of Git's cached filesystem metadata."""
    staged = _run_git(repo_root, "ls-files", "--stage", "-z", force_worktree=True)
    if staged.returncode != 0:
        raise OSError("could not inspect index objects")
    dirty: set[str] = set()
    regular: list[tuple[str, str]] = []
    for record in filter(None, staged.stdout.split("\0")):
        metadata, path = record.split("\t", 1)
        mode, object_id, stage = metadata.split()
        if stage != "0":
            continue  # Unmerged entries are already reported by status.
        target = repo_root / path
        if mode == "160000":
            if (target / ".git").exists() and _content_dirty_paths(target):
                dirty.add(path)
            continue
        try:
            file_mode = target.lstat().st_mode
        except (FileNotFoundError, NotADirectoryError):
            dirty.add(path)  # The preflight has already rejected skip-worktree entries.
            continue
        if mode == "120000" and stat.S_ISLNK(file_mode):
            hashed = _run_git(repo_root, "hash-object", "--stdin", input_text=os.readlink(target), force_worktree=True)
        elif mode in {"100644", "100755"} and stat.S_ISREG(file_mode):
            if "\n" in path or "\r" in path:
                raise OSError("tracked path cannot be safely batched for content inspection")
            regular.append((path, object_id))
            continue
        else:
            dirty.add(path)
            continue
        if hashed.returncode != 0:
            raise OSError("could not hash tracked content")
        if hashed.stdout.strip() != object_id:
            dirty.add(path)
    if regular:
        # --stdin-paths applies each path's staging conversions in one Git process.
        # Preflight has rejected attributes that could execute a filter.
        paths = "\n".join('"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"' for path, _ in regular) + "\n"
        hashed = _run_git(repo_root, "hash-object", "--stdin-paths", input_text=paths, force_worktree=True)
        object_ids = hashed.stdout.splitlines()
        if hashed.returncode != 0 or len(object_ids) != len(regular):
            raise OSError("could not hash tracked content")
        mismatched = [
            (path, expected) for (path, expected), actual in zip(regular, object_ids, strict=True) if actual != expected
        ]
        if mismatched:
            # Git preserves an index blob's raw CRLF bytes when autocrlf changes
            # after staging. A raw match is clean even if a new conversion differs.
            raw_paths = (
                "\n".join('"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"' for path, _ in mismatched) + "\n"
            )
            raw = _run_git(
                repo_root, "hash-object", "--stdin-paths", "--no-filters", input_text=raw_paths, force_worktree=True
            )
            raw_ids = raw.stdout.splitlines()
            if raw.returncode != 0 or len(raw_ids) != len(mismatched):
                raise OSError("could not hash tracked content without conversions")
            dirty.update(
                path for (path, expected), actual in zip(mismatched, raw_ids, strict=True) if actual != expected
            )
    return dirty


def validate_pr_sweep_dirty_closeout(
    repo_root: Path, *, ledger_path: Path | None = None, require_clean: bool = False
) -> PrSweepValidationResult:
    """Account for dirt observed in a private snapshot, never waive cleanliness.

    The result describes the copied state, not a lock on the primary checkout.
    Concurrent source edits during or after copying need a new validation run;
    copying and inspection do not provide an atomic primary-checkout assertion.
    """
    try:
        top_level = _run_git(repo_root, "rev-parse", "--show-toplevel")
        if top_level.returncode != 0 or Path(top_level.stdout.strip()).resolve() != repo_root.resolve():
            return _failure(
                "dirty_closeout", "blocked", "invalid_repo_root", "supplied root is not a worktree top level"
            )
        if not _ambient_status_config_is_supported(repo_root):
            return _failure(
                "dirty_closeout", "blocked", "ambient_git_config", "ambient Git status configuration is unsupported"
            )
        with TemporaryDirectory(prefix="sdk-pr-sweep-") as directory:
            private_root = Path(directory).resolve()
            if private_root.is_relative_to(repo_root.resolve()):
                raise OSError("snapshot must be outside source checkout")
            snapshot = _snapshot_worktree(repo_root, private_root)
            if not _git_metadata_is_private(snapshot, private_root):
                raise OSError("snapshot metadata leaves private directory")
            if _git_config_has_includes(snapshot) is not False:
                return _failure(
                    "dirty_closeout", "blocked", "git_config_include", "Git config paths prevent private inspection"
                )
            blocker_code, blocker_message = _git_status_preflight(snapshot, private_root=private_root)
            if blocker_code is not None and blocker_message is not None:
                return _failure("dirty_closeout", "blocked", blocker_code, blocker_message)
            completed = _run_git(
                snapshot,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=none",
                force_worktree=True,
            )
            content_dirty = _content_dirty_paths(snapshot)
    except (OSError, UnicodeError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        return _failure("dirty_closeout", "blocked", "git_status_unavailable", "could not inspect Git dirty state")
    if completed.returncode != 0:
        return _failure(
            "dirty_closeout", "blocked", "git_status_unavailable", "Git status failed in the supplied repository root"
        )
    try:
        state = _parse_porcelain(completed.stdout)
        state = PrSweepDirtyState(
            staged_paths=state.staged_paths,
            unstaged_paths=tuple(sorted(set(state.unstaged_paths) | content_dirty)),
            untracked_paths=state.untracked_paths,
            dirty_paths=tuple(sorted(set(state.dirty_paths) | content_dirty)),
        )
    except (ValueError, ContractError):
        return _failure("dirty_closeout", "blocked", "git_status_unavailable", "could not verify Git dirty paths")
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
