"""Installed public presentation proof with and without the images extra."""

from __future__ import annotations

import argparse
import importlib.util
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory


def _png() -> bytes:
    """Build a tiny static fixture using only standard-library codecs."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", 48, 48, 8, 2, 0, 0, 0)
    pixels = (b"\0" + b"\xff" * (48 * 3)) * 48
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def _request(root: Path, image_path: str) -> dict[str, object]:
    from skills_sdk.validation import validate_plugin_package

    capture = validate_plugin_package(root, source_revision="1" * 40)
    assert capture.status == "pass"
    candidate = capture.candidate.model_dump(mode="json")
    image = next(item for item in capture.files if item.path == image_path)
    return {
        "candidate": candidate,
        "mode_manifest_sha256": capture.mode_manifest_sha256,
        "image_approvals": [
            {
                "candidate": candidate,
                "image_path": image_path,
                "image_sha256": image.sha256,
                "kind": "icon",
                "professional": True,
                "rights_confirmed": True,
                "recognisable": True,
                "small_size": True,
                "light_dark": True,
                "distinctive": True,
                "evidence_ref": "synthetic:icon",
                "evidence_sha256": "a" * 64,
            }
        ],
        "copy_approval": {
            "candidate": candidate,
            "openai_settings_sha256": capture.manifest.openai_settings_sha256,
            "accurate": True,
            "evidence_ref": "synthetic:copy",
            "evidence_sha256": "b" * 64,
        },
    }


def _check(
    root: Path,
    path: str,
    expected: str,
    blocker: str | None = None,
    *,
    retained_request: dict[str, object] | None = None,
) -> None:
    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.validation import check_plugin_presentation

    request = retained_request if retained_request is not None else _request(root, path)
    result = check_plugin_presentation(root, source_revision="1" * 40, request=request)
    assert result.status == expected, result.model_dump(mode="json")
    if blocker is not None:
        assert result.findings[0].code == blocker
    SchemaRegistry().validate("plugin-presentation-check.v1", result.model_dump(mode="json"))
    forged = result.model_dump(mode="json")
    forged["release_ready"] = True
    try:
        SchemaRegistry().validate("plugin-presentation-check.v1", forged)
    except ContractError:
        pass
    else:
        raise AssertionError("schema accepted forged release authority")
    request_path = root.parent / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    command = subprocess.run(
        [
            sys.executable,
            "-m",
            "skills_sdk.cli.main",
            "check-plugin-presentation",
            str(root),
            "--source-revision",
            "1" * 40,
            "--request",
            str(request_path),
            "--json",
            "--robot",
        ],
        cwd=root.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert command.returncode == (0 if expected == "pass" else 2), command.stderr + command.stdout
    output = json.loads(command.stdout)
    assert output["status"] == expected and not output["release_ready"] and not output["host_display_observed"]
    if blocker is not None:
        assert output["findings"][0]["code"] == blocker


def _retained_approval_drift(root: Path, path: str) -> None:
    """Valid source changes require renewed synthetic approval, not reused clearance."""
    image = root / path
    original, mode = image.read_bytes(), image.stat().st_mode
    retained = _request(root, path)
    _check(root, path, "pass", retained_request=retained)
    image.write_bytes(original.replace(b"<rect ", b'<rect fill="#000" '))
    _check(root, path, "blocked", "plugin_presentation_binding_mismatch", retained_request=retained)
    _check(root, path, "pass")
    image.write_bytes(original)
    _check(root, path, "pass", retained_request=retained)
    image.chmod(mode ^ 0o100)
    _check(root, path, "blocked", "plugin_presentation_binding_mismatch", retained_request=retained)
    _check(root, path, "pass")
    image.chmod(mode)
    _check(root, path, "pass", retained_request=retained)


def _manifest(root: Path, image: str, *, screenshot: bool = False) -> None:
    interface: dict[str, object] = {"logo": "./" + image, "composerIcon": "./" + image}
    if screenshot:
        interface["screenshots"] = ["./" + image]
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                "name": "presentation-fixture",
                "extensions": {"com.openai": {"interface": interface}},
            }
        ),
        encoding="utf-8",
    )


def main() -> int:
    """Run from an installed wheel without repository fixtures or sibling code."""
    import skills_sdk

    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--without-images", action="store_true")
    modes.add_argument("--with-images", action="store_true")
    arguments = parser.parse_args()
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    assert (importlib.util.find_spec("PIL") is None) == arguments.without_images
    with TemporaryDirectory(prefix="sdk-installed-presentation-") as directory:
        root = Path(directory).resolve() / "plugin"
        (root / "assets").mkdir(parents=True)
        skill = root / "skills" / "presentation-fixture"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: presentation-fixture\ndescription: Summarise supplied fixture notes.\n---\n"
            "# Presentation fixture\n\nUse only the supplied notes and report missing evidence.\n",
            encoding="utf-8",
        )
        svg = "assets/icon.svg"
        (root / svg).write_bytes(
            b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="48" height="48"/></svg>'
        )
        _manifest(root, svg)
        _check(root, svg, "pass")
        _retained_approval_drift(root, svg)
        _manifest(root, svg, screenshot=True)
        _check(root, svg, "blocked", "plugin_presentation_images_invalid")
        _manifest(root, svg)
        _check(root, svg, "pass")
        raster = "assets/icon.png"
        image = _png()
        (root / raster).write_bytes(image)
        _manifest(root, raster, screenshot=True)
        if arguments.without_images:
            _check(root, raster, "blocked", "image_decoder_unavailable")
        else:
            _check(root, raster, "pass")
            (root / raster).write_bytes(image[: len(image) // 2])
            _check(root, raster, "blocked", "plugin_presentation_images_invalid")
            (root / raster).write_bytes(image)
            _check(root, raster, "pass")
        help_result = subprocess.run(
            [sys.executable, "-m", "skills_sdk.cli.main", "--help"],
            cwd=root.parent,
            capture_output=True,
            text=True,
            check=False,
        )
        assert help_result.returncode == 0 and "check-plugin-presentation" in help_result.stdout
    print("installed presentation public API/schema/CLI: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
