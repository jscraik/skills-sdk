"""Read-only verification for canonical portable package archives."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile, ZipInfo

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import Sha256
from skills_sdk.models.packaging import (
    PackageArchiveVerificationPolicy,
    PackageArchiveVerificationReceipt,
    PackageManifest,
    PackageReceiptBlocker,
    PackageReceiptV2,
)

_MANIFEST_PATH = "package-manifest.json"
_EOCD_SIGNATURE = b"PK\x05\x06"
_EOCD_SIZE = 22
_CENTRAL_SIGNATURE = b"PK\x01\x02"
_CENTRAL_HEADER_SIZE = 46
_MAX_ZIP_COMMENT_BYTES = 65_535


def _blocked(code: str, message: str, evidence: tuple[str, ...] = ()) -> PackageArchiveVerificationReceipt:
    return PackageArchiveVerificationReceipt(
        status="blocked",
        blocker=PackageReceiptBlocker(code=code, message=message, evidence_refs=evidence),
    )


def _entry_path(info: ZipInfo) -> str | None:
    name = info.filename
    if "\x00" in info.orig_filename or info.orig_filename != name or info.is_dir():
        return None
    try:
        require_portable_relative_path(name)
    except ValueError:
        return None
    return name


def _is_symlink(info: ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _sha256_stream(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object member: {key}")
        result[key] = value
    return result


def _preflight_central_directory(snapshot: bytes, policy: PackageArchiveVerificationPolicy) -> bool:
    search_start = max(0, len(snapshot) - _EOCD_SIZE - _MAX_ZIP_COMMENT_BYTES)
    offset = snapshot.rfind(_EOCD_SIGNATURE, search_start)
    if offset < 0 or offset + _EOCD_SIZE > len(snapshot):
        return False
    disk, central_disk, disk_entries, total_entries, size, directory_offset, comment_size = struct.unpack_from(
        "<HHHHIIH", snapshot, offset + 4
    )
    if offset + _EOCD_SIZE + comment_size != len(snapshot):
        return False
    if disk != 0 or central_disk != 0 or disk_entries != total_entries:
        return False
    if total_entries == 0xFFFF or size == 0xFFFFFFFF or directory_offset == 0xFFFFFFFF:
        return False
    directory_start = offset - size
    if total_entries > policy.max_entry_count or directory_start < 0 or directory_offset > directory_start:
        return False
    cursor = directory_start
    observed_entries = 0
    while cursor < offset:
        if cursor + _CENTRAL_HEADER_SIZE > offset or snapshot[cursor : cursor + 4] != _CENTRAL_SIGNATURE:
            return False
        name_size, extra_size, entry_comment_size = struct.unpack_from("<HHH", snapshot, cursor + 28)
        cursor += _CENTRAL_HEADER_SIZE + name_size + extra_size + entry_comment_size
        observed_entries += 1
        if cursor > offset or observed_entries > policy.max_entry_count:
            return False
    return cursor == offset and observed_entries == total_entries


def _read_manifest(archive: ZipFile, info: ZipInfo) -> PackageManifest | None:
    try:
        payload = json.loads(archive.read(info), object_pairs_hook=_reject_duplicate_keys)
        return PackageManifest.model_validate(payload)
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        return None


def _validate_entries(
    infos: list[ZipInfo], policy: PackageArchiveVerificationPolicy
) -> tuple[dict[str, ZipInfo] | None, PackageArchiveVerificationReceipt | None]:
    if (
        len(infos) > policy.max_entry_count
        or sum(item.file_size for item in infos) > policy.max_total_uncompressed_bytes
    ):
        return None, _blocked("archive_invalid_zip", "archive exceeds configured verification bounds")
    entries: dict[str, ZipInfo] = {}
    for info in infos:
        path = _entry_path(info)
        if path is None:
            return None, _blocked("archive_path_invalid", "archive entry path is not portable")
        if path in entries:
            code = "archive_manifest_duplicate" if path == _MANIFEST_PATH else "archive_entry_duplicate"
            return None, _blocked(code, "archive entry path is duplicated", (path,))
        if info.flag_bits & 0x1:
            return None, _blocked("archive_unreadable", "encrypted archive entries are not supported", (path,))
        if _is_symlink(info):
            return None, _blocked("archive_symlink_forbidden", "archive symlink entries are forbidden", (path,))
        entries[path] = info
    return entries, None


def _verify_payload(
    archive: ZipFile, entries: dict[str, ZipInfo], manifest: PackageManifest
) -> PackageArchiveVerificationReceipt | None:
    payload = set(entries) - {_MANIFEST_PATH}
    declared = {item.path for item in manifest.files}
    if missing := sorted(declared - payload):
        return _blocked("archive_payload_missing", "archive is missing a declared payload", (missing[0],))
    if undeclared := sorted(payload - declared):
        return _blocked("archive_payload_undeclared", "archive contains an undeclared payload", (undeclared[0],))
    records = {item.path: item for item in manifest.files}
    for path in sorted(declared):
        info = entries[path]
        record = records[path]
        if info.file_size != record.size_bytes:
            return _blocked("archive_payload_size_mismatch", "payload size does not match the manifest", (path,))
        with archive.open(info) as stream:
            digest, observed_size = _sha256_stream(stream)
            if observed_size != info.file_size or observed_size != record.size_bytes:
                return _blocked("archive_payload_size_mismatch", "payload size does not match the manifest", (path,))
            if digest != record.sha256:
                return _blocked(
                    "archive_payload_digest_mismatch", "payload digest does not match the manifest", (path,)
                )
    return None


def _verify_bindings(
    manifest: PackageManifest,
    expected_receipt: PackageReceiptV2 | None,
) -> tuple[str | None, PackageArchiveVerificationReceipt | None]:
    if candidate_content_sha256(manifest.files) != manifest.candidate.content_sha256:
        return None, _blocked("archive_candidate_digest_mismatch", "manifest files do not match the candidate digest")
    package_digest = canonical_json_sha256(manifest.model_dump(mode="json"))
    if expected_receipt is not None:
        try:
            expected_receipt = PackageReceiptV2.model_validate(expected_receipt.model_dump(mode="json"))
        except (ValidationError, PydanticSerializationError):
            return None, _blocked("archive_receipt_invalid", "expected receipt violates its contract")
        if (
            expected_receipt.status != "built"
            or expected_receipt.candidate != manifest.candidate
            or expected_receipt.manifest != manifest
        ):
            return None, _blocked("archive_receipt_mismatch", "expected receipt does not bind this package archive")
        if expected_receipt.package_digest != package_digest:
            return None, _blocked(
                "archive_package_digest_mismatch", "package digest does not match the expected receipt"
            )
    return package_digest, None


def _read_snapshot(
    archive_path: Path, policy: PackageArchiveVerificationPolicy
) -> bytes | PackageArchiveVerificationReceipt:
    try:
        descriptor = os.open(archive_path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return _blocked("archive_missing", "package archive does not exist")
    except IsADirectoryError:
        return _blocked("archive_not_regular_file", "package archive is not a regular file")
    except OSError:
        return _blocked("archive_unreadable", "package archive cannot be read")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return _blocked("archive_not_regular_file", "package archive is not a regular file")
        if metadata.st_size > policy.max_archive_bytes:
            return _blocked("archive_invalid_zip", "archive exceeds configured verification bounds")
        with os.fdopen(descriptor, "rb", closefd=False) as archive_stream:
            return archive_stream.read(policy.max_archive_bytes + 1)
    except OSError:
        return _blocked("archive_unreadable", "package archive cannot be read")
    finally:
        os.close(descriptor)


def verify_package_archive(
    archive_path: Path,
    *,
    expected_archive_sha256: Sha256 | None = None,
    expected_package_receipt: PackageReceiptV2 | None = None,
    policy: PackageArchiveVerificationPolicy | None = None,
) -> PackageArchiveVerificationReceipt:
    """Verify a canonical package ZIP without extracting or mutating it."""

    active_policy = policy or PackageArchiveVerificationPolicy()
    snapshot = _read_snapshot(archive_path, active_policy)
    if isinstance(snapshot, PackageArchiveVerificationReceipt):
        return snapshot
    with BytesIO(snapshot) as archive_stream:
        if len(snapshot) > active_policy.max_archive_bytes:
            return _blocked("archive_invalid_zip", "archive exceeds configured verification bounds")
        if not _preflight_central_directory(snapshot, active_policy):
            return _blocked("archive_invalid_zip", "archive central directory violates verification bounds")
        archive_digest = hashlib.sha256(snapshot).hexdigest()
        if expected_archive_sha256 is not None and archive_digest != expected_archive_sha256:
            return _blocked("archive_digest_mismatch", "archive digest does not match the expected digest")
        try:
            with ZipFile(archive_stream) as archive:
                entries, failure = _validate_entries(archive.infolist(), active_policy)
                if failure is not None:
                    return failure
                assert entries is not None
                manifest_info = entries.get(_MANIFEST_PATH)
                if manifest_info is None:
                    return _blocked("archive_manifest_missing", "canonical package manifest is missing")
                manifest = _read_manifest(archive, manifest_info)
                if manifest is None:
                    return _blocked(
                        "archive_manifest_invalid", "canonical package manifest is invalid", (_MANIFEST_PATH,)
                    )
                if failure := _verify_payload(archive, entries, manifest):
                    return failure
                package_digest, failure = _verify_bindings(manifest, expected_package_receipt)
                if failure is not None:
                    return failure
        except RuntimeError:
            return _blocked("archive_unreadable", "package archive contains an unreadable entry")
        except (BadZipFile, OSError):
            return _blocked("archive_invalid_zip", "package archive is not a readable ZIP")
    assert package_digest is not None
    return PackageArchiveVerificationReceipt(
        status="pass",
        archive_sha256=archive_digest,
        candidate=manifest.candidate,
        package_digest=package_digest,
        manifest=manifest,
        verified_files=tuple(item.path for item in manifest.files),
    )


__all__ = ["verify_package_archive"]
