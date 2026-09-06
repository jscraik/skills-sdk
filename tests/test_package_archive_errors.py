from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZIP_LZMA, ZIP_STORED, ZipExtFile, ZipFile

import pytest
from jsonschema import Draft202012Validator

from skills_sdk.core.errors import ContractError
from skills_sdk.core.receipts import parse_receipt
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.packaging import PackageArchiveVerificationPolicy
from skills_sdk.packaging import verify_package_archive
from tests.test_package_archive_verification import (
    _archive,
    _blocker_code,
    _manifest,
    _receipt,
    _set_member_uncompressed_size,
)


@pytest.mark.parametrize("member", ["package-manifest.json", "SKILL.md"])
def test_corrupt_deflate_returns_blocker(tmp_path: Path, member: str) -> None:
    path = tmp_path / "corrupt.zip"
    _archive(path)
    with ZipFile(path) as archive:
        offset = archive.getinfo(member).header_offset
    data = bytearray(path.read_bytes())
    name_size, extra_size = struct.unpack_from("<HH", data, offset + 26)
    data[offset + 30 + name_size + extra_size] = 7
    path.write_bytes(data)
    assert _blocker_code(path) == "archive_invalid_zip"


def test_invalid_utf8_filename_returns_blocker(tmp_path: Path) -> None:
    path = tmp_path / "bad-name.zip"
    _archive(path)
    data = bytearray(path.read_bytes())
    central = data.index(b"PK\x01\x02")
    struct.pack_into("<H", data, central + 8, 0x800)
    data[central + 46] = 0xFF
    path.write_bytes(data)
    assert _blocker_code(path) == "archive_invalid_zip"


@pytest.mark.parametrize("member", ["package-manifest.json", "SKILL.md"])
def test_truncated_entry_eof_returns_blocker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str) -> None:
    path = tmp_path / "truncated.zip"
    _archive(path)
    original = ZipExtFile.read

    def truncated(stream: ZipExtFile, n: int = -1) -> bytes:
        if stream.name == member:
            raise EOFError("truncated test entry")
        return original(stream, n)

    monkeypatch.setattr(ZipExtFile, "read", truncated)
    assert _blocker_code(path) == "archive_invalid_zip"


@pytest.mark.parametrize("codec", [ZIP_BZIP2, ZIP_LZMA])
def test_unbounded_codecs_rejected_before_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, codec: int) -> None:
    path = tmp_path / "unsupported.zip"
    with ZipFile(path, "w", codec) as archive:
        archive.writestr("package-manifest.json", b"{}")

    def unexpected_read(*args: object, **kwargs: object) -> None:
        pytest.fail("unsupported codec reached decompression")

    monkeypatch.setattr(ZipFile, "open", unexpected_read)
    assert _blocker_code(path) == "archive_invalid_zip"


@pytest.mark.parametrize("codec", [ZIP_STORED, ZIP_DEFLATED])
def test_bounded_codecs_and_receipt_compatibility(tmp_path: Path, codec: int) -> None:
    path = tmp_path / "valid.zip"
    payload = b"# Example\n"
    manifest = _manifest({"SKILL.md": payload})
    with ZipFile(path, "w", codec) as archive:
        archive.writestr("package-manifest.json", json.dumps(manifest.model_dump(mode="json")))
        archive.writestr("SKILL.md", payload)
    result = verify_package_archive(path, expected_package_receipt=_receipt(manifest))
    assert result.status == "pass"
    SchemaRegistry().validate("package-archive-verification.v1", result.model_dump(mode="json"))
    with pytest.raises(ContractError) as error:
        parse_receipt(result.model_dump(mode="json"))
    assert error.value.code == "unsupported_receipt_family"
    assert parse_receipt(_receipt(manifest).model_dump(mode="json")).artifact_status == "built"


def test_manifest_observed_length_must_match_metadata(tmp_path: Path) -> None:
    path = tmp_path / "length.zip"
    _archive(path)
    with ZipFile(path) as archive:
        size = archive.getinfo("package-manifest.json").file_size
    _set_member_uncompressed_size(path, "package-manifest.json", size + 10)
    assert _blocker_code(path) == "archive_manifest_invalid"


@pytest.mark.parametrize(("size", "valid"), [("1", False), (True, False), (1.0, True), (1, True)])
def test_manifest_field_types_match_packaged_schema(tmp_path: Path, size: object, valid: bool) -> None:
    path = tmp_path / "typed.zip"
    manifest = _manifest({"SKILL.md": b"x"})
    payload = manifest.model_dump(mode="json")
    payload["files"][0]["size_bytes"] = size
    assert Draft202012Validator(SchemaRegistry().load("package-manifest.v1")).is_valid(payload) is valid
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("package-manifest.json", json.dumps(payload))
        archive.writestr("SKILL.md", b"x")
    result = verify_package_archive(path, expected_package_receipt=_receipt(manifest))
    assert result.status == ("pass" if valid else "blocked")
    if not valid:
        assert result.blocker.code == "archive_manifest_invalid"


@pytest.mark.parametrize("limit", [2**63 - 1, 2**100])
def test_large_archive_limit_has_defined_behavior(tmp_path: Path, limit: int) -> None:
    path = tmp_path / "small.zip"
    _archive(path)
    result = verify_package_archive(path, policy=PackageArchiveVerificationPolicy(max_archive_bytes=limit))
    assert result.status == "pass"


@pytest.mark.parametrize("member", ["package-manifest.json", "SKILL.md"])
@pytest.mark.parametrize("local_codec", [ZIP_STORED, ZIP_LZMA])
def test_local_and_central_compression_must_agree(tmp_path: Path, member: str, local_codec: int) -> None:
    path = tmp_path / "headers.zip"
    _archive(path)
    with ZipFile(path) as archive:
        offset = archive.getinfo(member).header_offset
    data = bytearray(path.read_bytes())
    struct.pack_into("<H", data, offset + 8, local_codec)
    path.write_bytes(data)
    assert _blocker_code(path) == "archive_invalid_zip"


def test_embedded_nul_path_returns_blocker() -> None:
    assert _blocker_code(Path("invalid\x00archive.zip")) == "archive_unreadable"


@pytest.mark.parametrize("comment", [b"", b"ordinary comment", b"PK\x05\x06", b"PK\x05\x06" + bytes(18)])
def test_zip_comments_do_not_hide_the_eocd(tmp_path: Path, comment: bytes) -> None:
    path = tmp_path / "comment.zip"
    manifest = _archive(path)
    with ZipFile(path, "a") as archive:
        archive.comment = comment
    before = path.read_bytes()
    result = verify_package_archive(
        path, expected_archive_sha256=hashlib.sha256(before).hexdigest(), expected_package_receipt=_receipt(manifest)
    )
    assert result.status == "pass"
    assert path.read_bytes() == before


def test_competing_nonempty_zip_directories_are_blocked(tmp_path: Path) -> None:
    outer = tmp_path / "outer.zip"
    inner = tmp_path / "inner.zip"
    _archive(outer)
    _archive(inner)
    with ZipFile(outer, "a") as archive:
        archive.comment = inner.read_bytes()
    assert _blocker_code(outer) == "archive_invalid_zip"
