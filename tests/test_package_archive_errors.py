from __future__ import annotations

import json
import struct
from pathlib import Path
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZIP_LZMA, ZIP_STORED, ZipExtFile, ZipFile

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.core.receipts import parse_receipt
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.packaging import verify_package_archive
from tests.test_package_archive_verification import _archive, _blocker_code, _manifest, _receipt


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
