from __future__ import annotations

import hashlib
import json
import os
import struct
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import (
    PackageArchiveVerificationPolicy,
    PackageArchiveVerificationReceipt,
    PackageFileRole,
    PackageManifest,
    PackageManifestFile,
    PackageManifestProvenance,
    PackageReceiptBlocker,
    PackageReceiptV2,
)
from skills_sdk.packaging import archive_verification, verify_package_archive


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


def _set_member_uncompressed_size(path: Path, member_name: str, size: int) -> None:
    data = bytearray(path.read_bytes())
    encoded_name = member_name.encode()
    for signature, name_offset, size_offset in ((b"PK\x03\x04", 30, 22), (b"PK\x01\x02", 46, 24)):
        offset = 0
        while (offset := data.find(signature, offset)) >= 0:
            length_offset = offset + (26 if signature == b"PK\x03\x04" else 28)
            name_length = struct.unpack_from("<H", data, length_offset)[0]
            if bytes(data[offset + name_offset : offset + name_offset + name_length]) == encoded_name:
                struct.pack_into("<I", data, offset + size_offset, size)
            offset += len(signature)
    path.write_bytes(data)


def _set_eocd_entry_count(path: Path, count: int) -> None:
    data = bytearray(path.read_bytes())
    offset = data.rfind(b"PK\x05\x06")
    assert offset >= 0
    struct.pack_into("<HH", data, offset + 8, count, count)
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
    if name in {"duplicate", "duplicate_manifest"}:
        with pytest.warns(UserWarning, match="Duplicate name:") as warnings:
            writer(path)
        assert len(warnings) == 1
    else:
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
    assert _blocker_code(path, expected_package_receipt=mismatched_candidate) == "archive_receipt_invalid"
    mismatched_manifest = receipt.model_copy(update={"manifest": other})
    assert _blocker_code(path, expected_package_receipt=mismatched_manifest) == "archive_receipt_invalid"
    mismatched_digest = receipt.model_copy(update={"package_digest": "f" * 64})
    assert _blocker_code(path, expected_package_receipt=mismatched_digest) == "archive_receipt_invalid"
    invalid = receipt.model_copy(update={"mutation_performed": True})
    assert _blocker_code(path, expected_package_receipt=invalid) == "archive_receipt_invalid"
    invalid = receipt.model_copy(update={"included_files": ()})
    assert _blocker_code(path, expected_package_receipt=invalid) == "archive_receipt_invalid"
    invalid = receipt.model_copy(update={"blocker": PackageReceiptBlocker(code="invalid", message="invalid")})
    assert _blocker_code(path, expected_package_receipt=invalid) == "archive_receipt_invalid"
    invalid = PackageReceiptV2.model_construct(**{**receipt.__dict__, "mutation_performed": True})
    assert _blocker_code(path, expected_package_receipt=invalid) == "archive_receipt_invalid"


def test_rejects_archive_over_raw_byte_limit(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    _archive(path)
    size = path.stat().st_size
    accepted = verify_package_archive(path, policy=PackageArchiveVerificationPolicy(max_archive_bytes=size))
    assert accepted.status == "pass"
    blocker = _blocker_code(path, policy=PackageArchiveVerificationPolicy(max_archive_bytes=size - 1))
    assert blocker == "archive_invalid_zip"


def test_rejects_entry_count_before_zipfile_construction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "package.zip"
    _write_entries(path, [("one", b""), ("two", b"")])
    _set_eocd_entry_count(path, 1)

    def unexpected_zipfile(*args: object, **kwargs: object) -> None:
        raise AssertionError("ZipFile must not parse an out-of-policy central directory")

    monkeypatch.setattr(archive_verification, "ZipFile", unexpected_zipfile)
    policy = PackageArchiveVerificationPolicy(max_entry_count=1)
    assert _blocker_code(path, policy=policy) == "archive_invalid_zip"


def test_rejects_short_decompressed_payload(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    payload = b"A"
    manifest = _manifest({"payload": payload})
    record = manifest.files[0].model_copy(update={"size_bytes": 9})
    forged = manifest.model_copy(
        update={
            "files": (record,),
            "candidate": manifest.candidate.model_copy(update={"content_sha256": candidate_content_sha256((record,))}),
        }
    )
    _archive(path, payloads={"payload": payload}, manifest=forged)
    _set_member_uncompressed_size(path, "payload", 9)
    assert _blocker_code(path) == "archive_payload_size_mismatch"


def test_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    path = tmp_path / "package.fifo"
    os.mkfifo(path)
    assert _blocker_code(path) == "archive_not_regular_file"


@pytest.mark.parametrize("stage", ["fstat", "fdopen", "read"])
def test_snapshot_io_failure_is_typed_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    path = tmp_path / "package.zip"
    _archive(path)
    descriptors: list[int] = []
    original_open = os.open

    def tracked_open(*args: object, **kwargs: object) -> int:
        descriptor = original_open(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    with monkeypatch.context() as patch:
        patch.setattr(archive_verification.os, "open", tracked_open)
        failure = MagicMock(side_effect=OSError("injected snapshot failure"))
        if stage == "read":
            stream = MagicMock()
            stream.__enter__.return_value = stream
            stream.read = failure
            patch.setattr(archive_verification.os, "fdopen", MagicMock(return_value=stream))
        else:
            patch.setattr(archive_verification.os, stage, failure)
        assert _blocker_code(path) == "archive_unreadable"
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_unserializable_forged_receipt_returns_typed_blocker(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    receipt = _receipt(_archive(path))
    forged = receipt.model_copy(update={"receipt_id": object()})
    assert _blocker_code(path, expected_package_receipt=forged) == "archive_receipt_invalid"


def test_rejects_duplicate_manifest_object_members(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    manifest = _manifest({"SKILL.md": b"# Example\n"})
    payload = json.dumps(manifest.model_dump(mode="json"))
    duplicated = payload.replace('{"schema_version":', '{"schema_version":"package-manifest/v1","schema_version":', 1)
    _write_entries(path, [("package-manifest.json", duplicated.encode()), ("SKILL.md", b"# Example\n")])
    assert _blocker_code(path) == "archive_manifest_invalid"


def test_rejects_duplicate_nested_manifest_members(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    manifest = _manifest({"SKILL.md": b"# Example\n"})
    payload = json.dumps(manifest.model_dump(mode="json"))
    duplicated = payload.replace('{"schema_version": "package-candidate/v1",', '{"package_id":"other",', 1)
    _write_entries(path, [("package-manifest.json", duplicated.encode()), ("SKILL.md", b"# Example\n")])
    assert _blocker_code(path) == "archive_manifest_invalid"


def test_archive_contracts_are_exported_from_model_facade() -> None:
    from skills_sdk.models import PackageArchiveVerificationPolicy as FacadePolicy
    from skills_sdk.models import PackageArchiveVerificationReceipt as FacadeReceipt

    assert FacadePolicy is PackageArchiveVerificationPolicy
    assert FacadeReceipt is PackageArchiveVerificationReceipt


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


def test_draft_schema_enforces_receipt_states_and_unique_paths(tmp_path: Path) -> None:
    schema_path = Path(__file__).parents[1] / "src/skills_sdk/schemas/package-archive-verification.v1.schema.json"
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    path = tmp_path / "package.zip"
    _archive(path)
    passed = verify_package_archive(path).model_dump(mode="json")
    blocked = verify_package_archive(tmp_path / "missing.zip").model_dump(mode="json")
    validator.validate(passed)
    validator.validate(blocked)
    for invalid in ({"status": "pass"}, {"status": "blocked"}):
        assert list(validator.iter_errors(invalid))
    duplicated = {**passed, "verified_files": [passed["verified_files"][0]] * 2}
    assert list(validator.iter_errors(duplicated))
    for field in ("archive_sha256", "candidate", "package_digest", "manifest"):
        assert list(validator.iter_errors({**passed, field: None}))
    assert list(validator.iter_errors({**passed, "verified_files": []}))
    assert list(validator.iter_errors({**passed, "blocker": blocked["blocker"]}))
    assert list(validator.iter_errors({**blocked, "blocker": None}))
    for field in ("archive_sha256", "candidate", "package_digest", "manifest"):
        assert list(validator.iter_errors({**blocked, field: passed[field]}))
    assert list(validator.iter_errors({**blocked, "verified_files": passed["verified_files"]}))


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
    digest_payload = verify_package_archive(tmp_path / "missing.zip").model_dump(mode="json")
    digest_payload["archive_sha256"] = "a" * 64
    with pytest.raises(ValidationError, match="cannot claim package proof"):
        PackageArchiveVerificationReceipt.model_validate(digest_payload)
    with pytest.raises(ContractError, match="rejected the payload"):
        SchemaRegistry().validate("package-archive-verification.v1", digest_payload)
    schema_path = Path(__file__).parents[1] / "src/skills_sdk/schemas/package-archive-verification.v1.schema.json"
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    assert list(validator.iter_errors(digest_payload))


def test_rejects_raw_nul_entry_name(tmp_path: Path) -> None:
    path = tmp_path / "nul.zip"
    manifest = _manifest({"x": b"data"})
    _archive(path, payloads={"xAAAA": b"data"}, manifest=manifest)
    _inject_nul_into_payload_name(path)
    assert _blocker_code(path) == "archive_path_invalid"
