"""Read-only verification for canonical portable package archives."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile, ZipInfo

from pydantic import ValidationError

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


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(archive: ZipFile, info: ZipInfo) -> PackageManifest | None:
    try:
        payload = json.loads(archive.read(info))
        return PackageManifest.model_validate(payload)
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValidationError):
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
            if _sha256_stream(stream) != record.sha256:
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


def verify_package_archive(
    archive_path: Path,
    *,
    expected_archive_sha256: Sha256 | None = None,
    expected_package_receipt: PackageReceiptV2 | None = None,
    policy: PackageArchiveVerificationPolicy | None = None,
) -> PackageArchiveVerificationReceipt:
    """Verify a canonical package ZIP without extracting or mutating it."""

    try:
        archive_stream = archive_path.open("rb")
    except FileNotFoundError:
        return _blocked("archive_missing", "package archive does not exist")
    except IsADirectoryError:
        return _blocked("archive_not_regular_file", "package archive is not a regular file")
    except OSError:
        return _blocked("archive_unreadable", "package archive cannot be read")
    with archive_stream:
        if not stat.S_ISREG(os.fstat(archive_stream.fileno()).st_mode):
            return _blocked("archive_not_regular_file", "package archive is not a regular file")
        archive_digest = _sha256_stream(archive_stream)
        if expected_archive_sha256 is not None and archive_digest != expected_archive_sha256:
            return _blocked("archive_digest_mismatch", "archive digest does not match the expected digest")
        archive_stream.seek(0)
        try:
            with ZipFile(archive_stream) as archive:
                entries, failure = _validate_entries(archive.infolist(), policy or PackageArchiveVerificationPolicy())
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
