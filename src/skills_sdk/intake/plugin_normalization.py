"""Explicitly prepare a separate one-skill plugin candidate from standalone input."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from skills_sdk.core.digests import candidate_content_sha256
from skills_sdk.intake.normalization import intake_skill_package
from skills_sdk.models.intake import SkillPackageIntakeContext, SkillPackageIntakeReceipt
from skills_sdk.models.inventory import PackageType, SourceProvenance
from skills_sdk.models.package import (
    IntakeDecisionStatus,
    NormalizedPackage,
    PackageLifecycleState,
    PackageSource,
    PluginIdentity,
)
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.plugin import (
    PLUGIN_SCHEMA_URI,
    PluginCapturedFile,
    PluginPackageValidation,
    PluginValidationPolicy,
)
from skills_sdk.models.plugin_normalization import PluginNormalizationMetadata, PluginNormalizationReceipt
from skills_sdk.validation.plugin_capture import capture_plugin_source
from skills_sdk.validation.plugin_manifest import parse_plugin_manifest
from skills_sdk.validation.plugin_package import plugin_candidate_id, validate_plugin_package

_PLUGIN_POLICY = PluginValidationPolicy(require_version=True, require_description=True)
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


class _CandidateWriteError(OSError):
    """Keep whether this invocation created a partial output candidate."""

    def __init__(self, candidate_created: bool) -> None:
        super().__init__("safe candidate creation failed")
        self.candidate_created = candidate_created


class _DestinationExistsError(FileExistsError):
    """Distinguish an already-existing target from a partial write failure."""


def _block(
    intake: SkillPackageIntakeReceipt,
    code: str,
    message: str,
    *,
    candidate_created: bool = False,
    validation: PluginPackageValidation | None = None,
    refs: tuple[str, ...] = (),
) -> PluginNormalizationReceipt:
    """Retain source proof while returning a typed non-clearance result."""
    return PluginNormalizationReceipt(
        status="blocked",
        source_intake=intake,
        plugin_validation=validation,
        blocker=PackageReceiptBlocker(code=code, message=message, evidence_refs=refs),
        candidate_created=candidate_created,
    )


def _manifest_payload(metadata: PluginNormalizationMetadata) -> bytes:
    """Build only the canonical portable metadata requested by the caller."""
    values = {
        "$schema": PLUGIN_SCHEMA_URI,
        "name": metadata.name,
        "version": metadata.version,
        "description": metadata.description,
    }
    payload = (json.dumps(values, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    parse_plugin_manifest({"plugin.json": payload})
    PluginIdentity(package_id=plugin_candidate_id(metadata.name), name=metadata.name, version=metadata.version)
    return payload


def _same_skill_capture(intake: SkillPackageIntakeReceipt, files: tuple[PluginCapturedFile, ...]) -> bool:
    """Require copied standalone bytes to equal the already-admitted skill files."""
    expected = tuple((item.path, item.sha256, item.size_bytes) for item in intake.validation.files)
    observed = tuple((item.path, item.sha256, item.size_bytes) for item in files)
    return expected == observed


def _directory_paths(
    skill_name: str, source_directories: tuple[str, ...], files: tuple[PluginCapturedFile, ...]
) -> tuple[str, ...]:
    """Return unique plugin-relative directories in parent-before-child order."""
    paths = {"skills", f"skills/{skill_name}"}
    for item in (*source_directories, *(file.path.rpartition("/")[0] for file in files)):
        if item:
            parts = item.split("/")
            paths.update(f"skills/{skill_name}/" + "/".join(parts[:index]) for index in range(1, len(parts) + 1))
    return tuple(sorted(paths, key=lambda value: (value.count("/"), value)))


def _open_child_directory(parent: int, name: str, *, create: bool) -> int:
    """Open a directory relative to a trusted descriptor without following links."""
    if create:
        os.mkdir(name, 0o755, dir_fd=parent)
    return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)


def _create_directories(root: int, paths: tuple[str, ...]) -> None:
    """Create each candidate directory exclusively through no-follow descriptors."""
    for path in paths:
        parent = os.dup(root)
        try:
            parts = path.split("/")
            for component in parts[:-1]:
                child = _open_child_directory(parent, component, create=False)
                os.close(parent)
                parent = child
            child = _open_child_directory(parent, parts[-1], create=True)
            os.close(child)
        finally:
            os.close(parent)


def _write_file(root: int, path: str, payload: bytes, mode: int) -> None:
    """Create a candidate file exclusively below the opened root and preserve mode bits."""
    parent = os.dup(root)
    try:
        parts = path.split("/")
        for component in parts[:-1]:
            child = _open_child_directory(parent, component, create=False)
            os.close(parent)
            parent = child
        descriptor = os.open(
            parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
        try:
            with os.fdopen(os.dup(descriptor), "wb") as stream:
                stream.write(payload)
                stream.flush()
            os.fchmod(descriptor, stat.S_IMODE(mode) & 0o777)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def _destination_parent(source_root: Path, destination_root: Path) -> int:
    """Open an existing safe parent and reject a destination nested in its source."""
    if ".." in source_root.parts or ".." in destination_root.parts or not destination_root.name:
        raise ValueError("candidate paths must not contain parent traversal")
    source = source_root.resolve(strict=True)
    requested_parent = destination_root.parent.absolute()
    parent = requested_parent.resolve(strict=True)
    if parent == source or source in parent.parents:
        raise ValueError("candidate destination must be outside the standalone source")
    return _open_existing_directory(requested_parent)


def _open_existing_directory(path: Path) -> int:
    """Open an existing absolute directory without following any component."""
    if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
        raise OSError("safe candidate writes are unavailable on this host")
    from skills_sdk.validation.skill_package import _open_directory_tree

    return _open_directory_tree(path)


def _write_candidate(
    source_root: Path,
    destination_root: Path,
    manifest: bytes,
    skill_name: str,
    files: tuple[PluginCapturedFile, ...],
    payloads: dict[str, bytes],
    directories: tuple[str, ...],
) -> None:
    """Create a new candidate directory without replacing or following existing paths."""
    parent = _destination_parent(source_root, destination_root)
    candidate_created = False
    try:
        try:
            os.mkdir(destination_root.name, 0o755, dir_fd=parent)
        except FileExistsError as exc:
            raise _DestinationExistsError("candidate destination already exists") from exc
        candidate_created = True
        root = _open_child_directory(parent, destination_root.name, create=False)
        try:
            _create_directories(root, _directory_paths(skill_name, directories, files))
            _write_file(root, "plugin.json", manifest, 0o644)
            for record in files:
                _write_file(root, f"skills/{skill_name}/{record.path}", payloads[record.path], record.permission_mode)
            os.fsync(root)
        finally:
            os.close(root)
    except _DestinationExistsError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise _CandidateWriteError(candidate_created) from exc
    finally:
        os.close(parent)


def _normalized_package(intake: SkillPackageIntakeReceipt, validation: PluginPackageValidation) -> NormalizedPackage:
    """Bind whole-plugin identity to the admitted source owner and provenance."""
    assert intake.context is not None and intake.normalized_package is not None
    assert validation.candidate is not None and validation.manifest is not None
    context, candidate, manifest = intake.context, validation.candidate, validation.manifest
    identity = PluginIdentity(package_id=candidate.package_id, name=manifest.name, version=manifest.version or "")
    source = PackageSource(
        package_id=candidate.package_id,
        provenance=SourceProvenance(
            repository=context.source_repository,
            revision=context.source_revision,
            path=context.source_path,
            content_sha256=candidate.content_sha256,
        ),
        source_kind=context.source_kind,
    )
    return NormalizedPackage(
        package_type=PackageType.PLUGIN,
        identity=identity,
        source=source,
        owner=intake.normalized_package.owner,
        lifecycle=PackageLifecycleState.NORMALIZED,
    )


def _expected_plugin_files(
    manifest_payload: bytes,
    skill_name: str,
    files: tuple[PluginCapturedFile, ...],
) -> tuple[PluginCapturedFile, ...]:
    """Bind validation to the complete manifest and child bytes this call wrote."""
    expected = [
        PluginCapturedFile(
            path="plugin.json",
            sha256=hashlib.sha256(manifest_payload).hexdigest(),
            size_bytes=len(manifest_payload),
            permission_mode=0o644,
        )
    ]
    expected.extend(
        PluginCapturedFile(
            path=f"skills/{skill_name}/{item.path}",
            sha256=item.sha256,
            size_bytes=item.size_bytes,
            permission_mode=item.permission_mode,
        )
        for item in files
    )
    return tuple(sorted(expected, key=lambda item: item.path))


def normalize_standalone_skill_package(
    skill_root: Path,
    destination_root: Path,
    context: SkillPackageIntakeContext,
    metadata: PluginNormalizationMetadata,
) -> PluginNormalizationReceipt:
    """Create and freshly validate a separate complete-plugin candidate from admitted standalone input."""
    intake = intake_skill_package(skill_root, context)
    if intake.status != "normalized" or intake.decision is None:
        code = intake.blocker.code if intake.blocker is not None else "standalone_skill_blocked"
        refs = intake.blocker.evidence_refs if intake.blocker is not None else ()
        return _block(intake, code, "standalone skill intake did not pass", refs=refs)
    if intake.decision.decision is not IntakeDecisionStatus.ADMIT:
        code = intake.decision.blocker_codes[0]
        return _block(intake, code, "provenance, rights, or ownership evidence requires correction")
    try:
        metadata = PluginNormalizationMetadata.model_validate(metadata)
        manifest = _manifest_payload(metadata)
    except (TypeError, ValueError):
        return _block(intake, "plugin_metadata_invalid", "plugin metadata is invalid; correct it before normalization")
    try:
        files, payloads, directories = capture_plugin_source(skill_root)
    except (TypeError, ValueError):
        return _block(intake, "source_changed", "standalone source differs from its admitted capture")
    except OSError:
        return _block(intake, "standalone_source_unavailable", "standalone source cannot be safely captured")
    if not _same_skill_capture(intake, files):
        return _block(intake, "source_changed", "standalone source differs from its admitted capture")
    assert intake.validation.identity is not None
    try:
        _write_candidate(
            skill_root,
            destination_root,
            manifest,
            intake.validation.identity.name,
            files,
            payloads,
            directories,
        )
    except _DestinationExistsError:
        return _block(
            intake, "candidate_destination_exists", "candidate destination already exists; no files were replaced"
        )
    except _CandidateWriteError as exc:
        return _block(
            intake,
            "candidate_normalization_failed",
            "safe candidate normalization could not complete; inspect the requested destination",
            candidate_created=exc.candidate_created,
        )
    except (OSError, TypeError, ValueError):
        return _block(intake, "candidate_normalization_failed", "safe candidate normalization could not complete")
    return _validate_and_receipt(
        intake,
        skill_root,
        destination_root,
        context.source_revision,
        metadata,
        manifest,
        intake.validation.identity.name,
        files,
        payloads,
        directories,
    )


def _validate_and_receipt(
    intake: SkillPackageIntakeReceipt,
    skill_root: Path,
    destination_root: Path,
    source_revision: str,
    metadata: PluginNormalizationMetadata,
    manifest_payload: bytes,
    skill_name: str,
    files: tuple[PluginCapturedFile, ...],
    payloads: dict[str, bytes],
    directories: tuple[str, ...],
) -> PluginNormalizationReceipt:
    """Recheck source stability and bind fresh complete-plugin and child proof."""
    validation = validate_plugin_package(destination_root, source_revision=source_revision, policy=_PLUGIN_POLICY)
    try:
        current = capture_plugin_source(skill_root)
    except (OSError, TypeError, ValueError):
        return _block(
            intake,
            "source_recheck_failed",
            "candidate was created but standalone source stability could not be confirmed",
            candidate_created=True,
            validation=validation,
        )
    if (files, payloads, directories) != current:
        return _block(
            intake,
            "source_changed",
            "candidate was created but standalone source changed during normalization",
            candidate_created=True,
            validation=validation,
        )
    if validation.status != "pass" or validation.candidate is None:
        first = next(item for item in validation.findings if item.severity.value == "blocker")
        return _block(
            intake,
            first.code,
            "fresh whole-plugin validation blocked the normalized candidate",
            candidate_created=True,
            validation=validation,
            refs=first.evidence_refs,
        )
    if len(validation.skills) != 1 or validation.skills[0].validation.candidate != intake.candidate:
        return _block(
            intake,
            "standalone_candidate_binding_mismatch",
            "whole-plugin validation did not retain the admitted standalone skill identity",
            candidate_created=True,
            validation=validation,
        )
    expected_files = _expected_plugin_files(manifest_payload, skill_name, files)
    manifest = validation.manifest
    candidate = validation.candidate
    if (
        validation.files != expected_files
        or manifest.name != metadata.name
        or manifest.version != metadata.version
        or manifest.description != metadata.description
        or manifest.source_sha256 != hashlib.sha256(manifest_payload).hexdigest()
        or candidate.source_revision != source_revision
        or candidate.content_sha256 != candidate_content_sha256(expected_files)
    ):
        return _block(
            intake,
            "normalized_candidate_changed",
            (
                "destination no longer matches the manifest and source captured for this normalization; "
                "inspect it before retrying"
            ),
            candidate_created=True,
            validation=validation,
        )
    normalized = _normalized_package(intake, validation)
    return PluginNormalizationReceipt(
        status="prepared",
        source_intake=intake,
        plugin_validation=validation,
        normalized_package=normalized,
        candidate_created=True,
    )


__all__ = ["normalize_standalone_skill_package"]
