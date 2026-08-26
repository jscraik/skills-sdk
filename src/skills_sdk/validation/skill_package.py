"""Filesystem-safe validation for standalone Agent Skills packages."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.package import PackageCandidateIdentity, SkillIdentity
from skills_sdk.models.packaging import PackageFileRole, PackageManifestFile
from skills_sdk.models.validation import SkillPackageFinding, SkillPackageValidation, ValidationSeverity
from skills_sdk.validation.skill_ir import SkillIR, build_skill_ir, read_frontmatter

_ALLOWED_FRONTMATTER: Final[frozenset[str]] = frozenset(
    {"name", "description", "version", "license", "compatibility", "allowed-tools", "metadata", "triggers"}
)
_UNSAFE_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".agents",
        ".cache",
        ".codex",
        ".git",
        ".gnupg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".ssh",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)
_UNSAFE_NAMES: Final[frozenset[str]] = frozenset(
    {".env", "credentials.json", "id_rsa", "id_ed25519", "secrets.json"}
)
_PACKAGE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SOURCE_REVISION_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_MAX_PACKAGE_DIRECTORY_DEPTH: Final[int] = 64


class _UnsupportedSafeTraversal(OSError):
    """The host cannot enforce descriptor-relative no-follow traversal."""


@dataclass(frozen=True, slots=True)
class SkillValidationPolicy:
    """Injectable authoring limits; repository-specific values stay outside core."""

    max_entrypoint_lines: int | None = None
    max_reference_depth: int | None = None
    allowed_frontmatter: frozenset[str] = _ALLOWED_FRONTMATTER


def _read_regular_bytes(parent_fd: int, name: str) -> tuple[bytes, bool]:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise OSError(f"not a regular file: {name}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        stable = (before.st_size, before.st_mtime_ns, before.st_ino) == (
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
        )
        return b"".join(chunks), stable
    finally:
        os.close(descriptor)


def _open_directory_tree(path: Path) -> int:
    """Open every absolute path component without following symbolic links."""

    directory_flag = getattr(os, "O_DIRECTORY", None)
    nofollow_flag = getattr(os, "O_NOFOLLOW", None)
    if directory_flag is None or nofollow_flag is None or os.open not in os.supports_dir_fd:
        raise _UnsupportedSafeTraversal("safe descriptor-relative traversal is unavailable")
    flags = os.O_RDONLY | directory_flag | nofollow_flag
    absolute = path.absolute()
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _content_digest(files: list[PackageManifestFile]) -> str:
    digest = hashlib.sha256()
    for item in files:
        digest.update(item.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _finding(code: str, message: str, *refs: str) -> SkillPackageFinding:
    return SkillPackageFinding(
        code=code,
        severity=ValidationSeverity.BLOCKER,
        message=message,
        evidence_refs=tuple(refs),
    )


def _source_changed_finding(relative_directory: Path) -> SkillPackageFinding:
    references = (relative_directory.as_posix(),) if relative_directory.parts else ()
    return _finding("source_changed", "package directory changed during validation", *references)


def _candidate(package_root: Path, source_revision: str, files: list[PackageManifestFile]) -> PackageCandidateIdentity:
    content_sha256 = _content_digest(files) if files else hashlib.sha256(b"").hexdigest()
    package_id = package_root.name
    if not _PACKAGE_ID_RE.fullmatch(package_id):
        root_digest = hashlib.sha256(package_root.name.encode("utf-8", errors="surrogateescape")).hexdigest()[:6]
        package_id = f"invalid-package-{root_digest}-{content_sha256[:12]}"
    return PackageCandidateIdentity(
        package_id=package_id,
        source_revision=source_revision,
        content_sha256=content_sha256,
    )


def _file_role(relative: Path) -> PackageFileRole:
    if relative == Path("SKILL.md"):
        return PackageFileRole.SKILL_MD
    if relative == Path("README.md"):
        return PackageFileRole.README
    return {
        "references": PackageFileRole.REFERENCE,
        "scripts": PackageFileRole.SCRIPT,
        "assets": PackageFileRole.ASSET,
        "evals": PackageFileRole.EVAL,
    }.get(relative.parts[0], PackageFileRole.ASSET)


def _is_generated_receipt(name: str) -> bool:
    return name == "skill-package-validation.json" or name.endswith("-receipt.json")


def _regular_file(
    parent_fd: int, relative: Path, role: PackageFileRole
) -> tuple[PackageManifestFile | None, SkillPackageFinding | None, bytes | None]:
    relative_text = relative.as_posix()
    try:
        relative_text.encode("utf-8")
        require_portable_relative_path(relative_text)
    except (ContractError, UnicodeError):
        return None, _finding("invalid_package_path", "package filenames must be portable POSIX paths"), None
    name = relative.name
    if (
        name in _UNSAFE_NAMES
        or name.startswith(".env.")
        or _is_generated_receipt(name)
        or relative.suffix.lower() in {".key", ".pem", ".p12", ".pfx", ".token"}
    ):
        return (
            None,
            _finding("unsafe_package_file", "credential-like files cannot enter a package", relative_text),
            None,
        )
    try:
        payload, stable = _read_regular_bytes(parent_fd, name)
    except OSError:
        return (
            None,
            _finding("unreadable_package_file", "package file must remain a readable regular file", relative_text),
            None,
        )
    if not stable:
        return None, _finding("source_changed", "package source changed during validation", relative_text), None
    return (
        PackageManifestFile(
            path=relative_text,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            role=role,
        ),
        None,
        payload,
    )


def _scan_files(
    package_root: Path, policy: SkillValidationPolicy
) -> tuple[list[PackageManifestFile], list[SkillPackageFinding], dict[str, bytes]]:
    files: list[PackageManifestFile] = []
    findings: list[SkillPackageFinding] = []
    captured: dict[str, bytes] = {}
    try:
        root_fd = _open_directory_tree(package_root)
    except _UnsupportedSafeTraversal:
        return (
            files,
            [_finding("unsupported_platform", "host cannot enforce safe descriptor-relative traversal")],
            captured,
        )
    except OSError:
        return (
            files,
            [_finding("unreadable_package_root", "package root must support safe descriptor traversal")],
            captured,
        )

    def visit(directory_fd: int, relative_directory: Path, depth: int) -> None:
        before = os.fstat(directory_fd)
        try:
            entries = sorted(os.scandir(directory_fd), key=lambda entry: entry.name)
        except OSError:
            findings.append(
                _finding(
                    "unreadable_package_directory",
                    "package directory must remain readable",
                    relative_directory.as_posix(),
                )
            )
            return
        for entry in entries:
            relative_path = relative_directory / entry.name
            relative = relative_path.as_posix()
            try:
                relative.encode("utf-8")
                require_portable_relative_path(relative)
            except (ContractError, UnicodeError):
                findings.append(_finding("invalid_package_path", "package filenames must be portable POSIX paths"))
                continue
            if entry.name in _UNSAFE_DIRECTORIES:
                findings.append(
                    _finding(
                        "unsafe_package_directory",
                        "runtime and source-control directories cannot enter a package",
                        relative,
                    )
                )
                continue
            if entry.is_symlink():
                findings.append(_finding("symlink_not_allowed", "package paths must not be symbolic links", relative))
                continue
            if entry.is_dir(follow_symlinks=False):
                if depth >= _MAX_PACKAGE_DIRECTORY_DEPTH:
                    findings.append(
                        _finding(
                            "package_depth_exceeded",
                            f"package directory depth exceeds {_MAX_PACKAGE_DIRECTORY_DEPTH}",
                            relative,
                        )
                    )
                    continue
                try:
                    child_fd = os.open(
                        entry.name,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=directory_fd,
                    )
                except OSError:
                    findings.append(
                        _finding("unreadable_package_directory", "package directory must remain readable", relative)
                    )
                    continue
                try:
                    visit(child_fd, relative_path, depth + 1)
                finally:
                    os.close(child_fd)
                continue
            if (
                relative_path.parts[0] == "references"
                and policy.max_reference_depth is not None
                and len(relative_path.parts) - 1 > policy.max_reference_depth
            ):
                findings.append(
                    _finding(
                        "reference_depth_exceeded",
                        "reference depth "
                        f"{len(relative_path.parts) - 1} exceeds configured limit {policy.max_reference_depth}",
                        relative,
                    )
                )
            record, finding, payload = _regular_file(directory_fd, relative_path, _file_role(relative_path))
            if record is not None and payload is not None:
                files.append(record)
                captured[relative] = payload
            if finding is not None:
                findings.append(finding)
        after = os.fstat(directory_fd)
        if (before.st_mtime_ns, before.st_ino) != (after.st_mtime_ns, after.st_ino):
            findings.append(_source_changed_finding(relative_directory))

    try:
        visit(root_fd, Path(), 0)
    finally:
        os.close(root_fd)
    files.sort(key=lambda item: item.path)
    return files, findings, captured


def _validate_ir(
    package_root: Path,
    skill_text: str,
    ir: SkillIR,
    policy: SkillValidationPolicy,
) -> tuple[SkillIdentity | None, list[SkillPackageFinding]]:
    findings: list[SkillPackageFinding] = []
    if not ir.name_declared:
        findings.append(_finding("missing_name", "SKILL.md frontmatter requires a non-empty name", "SKILL.md"))
    elif ir.name != package_root.name:
        findings.append(_finding("name_mismatch", "skill name must match the package directory", "SKILL.md"))
    if not ir.description:
        findings.append(_finding("missing_description", "SKILL.md frontmatter requires a description", "SKILL.md"))
    unknown = sorted(set(ir.frontmatter) - policy.allowed_frontmatter)
    if unknown:
        findings.append(
            _finding("unknown_frontmatter", f"unsupported frontmatter keys: {', '.join(unknown)}", "SKILL.md")
        )
    if policy.max_entrypoint_lines is not None:
        line_count = len(skill_text.splitlines())
        if line_count > policy.max_entrypoint_lines:
            findings.append(
                _finding(
                    "entrypoint_line_budget_exceeded",
                    f"SKILL.md has {line_count} lines; configured limit is {policy.max_entrypoint_lines}",
                    "SKILL.md",
                )
            )
    identity: SkillIdentity | None = None
    if ir.name_declared and ir.name and ir.description and ir.name == package_root.name:
        try:
            identity = SkillIdentity(package_id=ir.name, name=ir.name, version=ir.version)
        except ValueError:
            findings.append(_finding("invalid_identity", "skill name or version is invalid", "SKILL.md"))
    return identity, findings


def validate_skill_package(
    package_root: Path,
    *,
    source_revision: str,
    policy: SkillValidationPolicy | None = None,
) -> SkillPackageValidation:
    """Validate a package without executing it or mutating its source tree."""

    active_policy = policy or SkillValidationPolicy()
    root = package_root.absolute()
    findings: list[SkillPackageFinding] = []
    files: list[PackageManifestFile] = []
    identity: SkillIdentity | None = None
    revision_is_valid = bool(_SOURCE_REVISION_RE.fullmatch(source_revision))
    if not revision_is_valid:
        findings.append(
            _finding("invalid_source_revision", "source revision must be a 40-character lowercase hexadecimal digest")
        )
    if not package_root.exists() or not package_root.is_dir() or package_root.is_symlink():
        findings.append(_finding("invalid_package_root", "package root must be a regular directory"))
    else:
        try:
            root.name.encode("utf-8")
        except UnicodeError:
            findings.append(_finding("invalid_package_path", "package directory name must be valid UTF-8"))
        if not _PACKAGE_ID_RE.fullmatch(root.name):
            findings.append(
                _finding("invalid_package_root", "package directory must use a portable package identifier")
            )
        skill_md = root / "SKILL.md"
        if not skill_md.exists() or not skill_md.is_file() or skill_md.is_symlink():
            findings.append(_finding("missing_skill_md", "package requires a regular SKILL.md", "SKILL.md"))
        else:
            files, file_findings, captured = _scan_files(root, active_policy)
            findings.extend(file_findings)
            try:
                skill_payload = captured.get("SKILL.md")
                if skill_payload is None:
                    raise OSError("SKILL.md was not captured as a regular file")
                text = skill_payload.decode("utf-8")
                _frontmatter, _body, closed = read_frontmatter(text)
                if not closed:
                    findings.append(_finding("invalid_frontmatter", "SKILL.md requires closed frontmatter", "SKILL.md"))
                else:
                    ir = build_skill_ir(skill_md, text=text)
                    identity, ir_findings = _validate_ir(root, text, ir, active_policy)
                    findings.extend(ir_findings)
            except UnicodeDecodeError:
                findings.append(_finding("invalid_utf8", "SKILL.md must be UTF-8", "SKILL.md"))
            except OSError:
                findings.append(
                    _finding("unreadable_skill_md", "SKILL.md must remain a readable regular file", "SKILL.md")
                )
            except (ValueError, yaml.YAMLError):
                findings.append(_finding("invalid_frontmatter", "SKILL.md frontmatter must be valid YAML", "SKILL.md"))
    candidate = _candidate(root, source_revision, files) if revision_is_valid else None
    status = "blocked" if any(item.severity is ValidationSeverity.BLOCKER for item in findings) else "pass"
    return SkillPackageValidation(
        candidate=candidate,
        status=status,
        identity=identity,
        files=tuple(files),
        findings=tuple(findings),
    )


__all__ = ["SkillValidationPolicy", "validate_skill_package"]
