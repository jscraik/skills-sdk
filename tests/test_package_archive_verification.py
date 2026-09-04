from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from pydantic import ValidationError

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import (
    PackageFileRole,
    PackageManifest,
    PackageManifestFile,
    PackageManifestProvenance,
    PackageReceiptV2,
)
from skills_sdk.packaging import verify_package_archive


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(payloads: dict[str, bytes]) -> PackageManifest:
    files = tuple(
        PackageManifestFile(path=path, sha256=_sha(data), size_bytes=len(data), role=PackageFileRole.ASSET)
        for path, data in sorted(payloads.items())
    )
    candidate = PackageCandidateIdentity(
        package_id="example-skill", source_revision="1" * 40, content_sha256=candidate_content_sha256(files)
    )
    return PackageManifest(
        schema_version="package-manifest/v1",
        candidate=candidate,
        version="1.0.0",
        files=files,
        provenance=PackageManifestProvenance(source=("SKILL.md",), builder="test-builder"),
    )


def _archive(
    path: Path, *, payloads: dict[str, bytes] | None = None, manifest: object | None = None
) -> PackageManifest:
    active_payloads = payloads or {"SKILL.md": b"# Example\n"}
    active_manifest = _manifest(active_payloads) if manifest is None else manifest
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "package-manifest.json",
            json.dumps(
                active_manifest.model_dump(mode="json")
                if isinstance(active_manifest, PackageManifest)
                else active_manifest
            ),
        )
        for name, data in active_payloads.items():
            archive.writestr(name, data)
    assert isinstance(active_manifest, PackageManifest)
    return active_manifest


def _receipt(manifest: PackageManifest) -> PackageReceiptV2:
    return PackageReceiptV2(
        schema_version="package-receipt/v2",
        receipt_id="example-receipt",
        candidate=manifest.candidate,
        lane="validation",
        status="built",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z",
        evidence=tuple(item.path for item in manifest.files),
        package_digest=canonical_json_sha256(manifest.model_dump(mode="json")),
        manifest=manifest,
        included_files=tuple(item.path for item in manifest.files),
    )


def _write_entries(path: Path, entries: list[tuple[str, bytes]]) -> None:
    with ZipFile(path, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)


def _write_symlink(path: Path) -> None:
    info = ZipInfo("link")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with ZipFile(path, "w") as archive:
        archive.writestr(info, "target")


def _write_duplicate_manifest(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("package-manifest.json", "{}")
        archive.writestr("package-manifest.json", "{}")


def _blocker_code(path: Path, **kwargs: object) -> str:
    result = verify_package_archive(path, **kwargs)
    assert result.blocker is not None
    return result.blocker.code


def _mark_first_entry_encrypted(path: Path) -> None:
    data = bytearray(path.read_bytes())
    local = data.index(b"PK\x03\x04")
    central = data.index(b"PK\x01\x02")
    data[local + 6 : local + 8] = (1).to_bytes(2, "little")
    data[central + 8 : central + 10] = (1).to_bytes(2, "little")
    path.write_bytes(data)


def _inject_nul_into_payload_name(path: Path) -> None:
    data = path.read_bytes().replace(b"xAAAA", b"x\x00AAA")
    path.write_bytes(data)


def test_accepts_canonical_archive_and_receipt(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    manifest = _archive(path)
    result = verify_package_archive(
        path, expected_archive_sha256=_sha(path.read_bytes()), expected_package_receipt=_receipt(manifest)
    )
    assert result.status == "pass"
    assert result.candidate == manifest.candidate
    assert result.archive_extracted is False
    assert result.mutation_performed is False
    SchemaRegistry().validate("package-archive-verification.v1", result.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("name", "writer", "code"),
    [
        ("invalid", lambda path: path.write_bytes(b"not zip"), "archive_invalid_zip"),
        ("missing_manifest", lambda path: ZipFile(path, "w").close(), "archive_manifest_missing"),
        (
            "bad_manifest",
            lambda path: _write_entries(path, [("package-manifest.json", b"{")]),
            "archive_manifest_invalid",
        ),
        ("absolute", lambda path: _write_entries(path, [("/bad", b"x")]), "archive_path_invalid"),
        ("drive", lambda path: _write_entries(path, [("C:/bad", b"x")]), "archive_path_invalid"),
        ("traversal", lambda path: _write_entries(path, [("../bad", b"x")]), "archive_path_invalid"),
        ("duplicate", lambda path: _write_entries(path, [("same", b"x"), ("same", b"x")]), "archive_entry_duplicate"),
        ("duplicate_manifest", _write_duplicate_manifest, "archive_manifest_duplicate"),
        ("symlink", _write_symlink, "archive_symlink_forbidden"),
    ],
)
def test_rejects_unsafe_archive_shapes(tmp_path: Path, name: str, writer: Callable[[Path], object], code: str) -> None:
    path = tmp_path / f"{name}.zip"
    writer(path)
    assert _blocker_code(path) == code


def test_missing_and_not_regular_file(tmp_path: Path) -> None:
    assert _blocker_code(tmp_path / "missing.zip") == "archive_missing"
    assert _blocker_code(tmp_path) == "archive_not_regular_file"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("missing", "archive_payload_missing"),
        ("undeclared", "archive_payload_undeclared"),
        ("size", "archive_payload_size_mismatch"),
        ("digest", "archive_payload_digest_mismatch"),
        ("candidate", "archive_candidate_digest_mismatch"),
    ],
)
def test_rejects_payload_and_candidate_mismatches(tmp_path: Path, mutation: str, code: str) -> None:
    path = tmp_path / "package.zip"
    payloads = {"SKILL.md": b"# Example\n"}
    manifest = _manifest(payloads)
    if mutation == "missing":
        _archive(path, payloads={"README.md": b"other"}, manifest=manifest)
    elif mutation == "undeclared":
        _archive(path, payloads={**payloads, "extra.txt": b"extra"}, manifest=manifest)
    elif mutation == "size":
        item = manifest.files[0].model_copy(update={"size_bytes": 999})
        _archive(path, payloads=payloads, manifest=manifest.model_copy(update={"files": (item,)}))
    elif mutation == "digest":
        item = manifest.files[0].model_copy(update={"sha256": "f" * 64})
        forged = manifest.model_copy(
            update={
                "files": (item,),
                "candidate": manifest.candidate.model_copy(
                    update={"content_sha256": candidate_content_sha256((item,))}
                ),
            }
        )
        _archive(path, payloads=payloads, manifest=forged)
    else:
        _archive(
            path,
            payloads=payloads,
            manifest=manifest.model_copy(
                update={"candidate": manifest.candidate.model_copy(update={"content_sha256": "f" * 64})}
            ),
        )
    assert _blocker_code(path) == code


def test_rejects_archive_digest_and_receipt_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    manifest = _archive(path)
    assert _blocker_code(path, expected_archive_sha256="f" * 64) == "archive_digest_mismatch"
    receipt = _receipt(manifest).model_copy(update={"receipt_id": "other"})
    assert verify_package_archive(path, expected_package_receipt=receipt).status == "pass"
    other = _manifest({"README.md": b"other"})
    assert _blocker_code(path, expected_package_receipt=_receipt(other)) == "archive_receipt_mismatch"
    mismatched_candidate = receipt.model_copy(update={"candidate": other.candidate})
    assert _blocker_code(path, expected_package_receipt=mismatched_candidate) == "archive_receipt_mismatch"
    mismatched_manifest = receipt.model_copy(update={"manifest": other})
    assert _blocker_code(path, expected_package_receipt=mismatched_manifest) == "archive_receipt_mismatch"
    mismatched_digest = receipt.model_copy(update={"package_digest": "f" * 64})
    assert _blocker_code(path, expected_package_receipt=mismatched_digest) == "archive_package_digest_mismatch"


def test_rejects_contract_invalid_manifest(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    _write_entries(path, [("package-manifest.json", b'{"schema_version":"wrong"}')])
    assert _blocker_code(path) == "archive_manifest_invalid"


def test_receipt_model_and_registry_reject_forged_pass(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    _archive(path)
    result = verify_package_archive(path)
    assert result.status == "pass"
    payload = result.model_dump(mode="json")
    payload["package_digest"] = "f" * 64
    with pytest.raises(ValidationError, match="package digest"):
        type(result).model_validate(payload)
    with pytest.raises(ContractError, match="rejected the payload"):
        SchemaRegistry().validate("package-archive-verification.v1", payload)


def test_rejects_encrypted_entry_with_typed_blocker(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.zip"
    _archive(path)
    _mark_first_entry_encrypted(path)
    assert _blocker_code(path) == "archive_unreadable"


def test_receipt_model_and_registry_reject_blocked_pass_proof(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    _archive(path)
    passed = verify_package_archive(path)
    payload = passed.model_dump(mode="json")
    payload.update(
        status="blocked",
        blocker={"code": "archive_invalid_zip", "message": "blocked", "evidence_refs": []},
    )
    with pytest.raises(ValidationError, match="cannot claim package proof"):
        type(passed).model_validate(payload)
    with pytest.raises(ContractError, match="rejected the payload"):
        SchemaRegistry().validate("package-archive-verification.v1", payload)


def test_rejects_raw_nul_entry_name(tmp_path: Path) -> None:
    path = tmp_path / "nul.zip"
    manifest = _manifest({"x": b"data"})
    _archive(path, payloads={"xAAAA": b"data"}, manifest=manifest)
    _inject_nul_into_payload_name(path)
    assert _blocker_code(path) == "archive_path_invalid"
