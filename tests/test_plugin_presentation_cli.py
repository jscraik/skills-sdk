"""Actual presentation CLI acceptance, bounded request rejection and recovery."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from skills_sdk.cli.main import main
from skills_sdk.validation import validate_plugin_package

REVISION = "1" * 40


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    root = tmp_path.resolve() / "fixture-plugin"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="48" height="48"/></svg>',
        encoding="utf-8",
    )
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                "name": "fixture-plugin",
                "extensions": {
                    "com.openai": {"interface": {"logo": "./assets/icon.svg", "composerIcon": "./assets/icon.svg"}}
                },
            }
        ),
        encoding="utf-8",
    )
    capture = validate_plugin_package(root, source_revision=REVISION)
    assert capture.status == "pass"
    image = next(item for item in capture.files if item.path == "assets/icon.svg")
    candidate = capture.candidate.model_dump(mode="json")
    request: dict[str, object] = {
        "candidate": candidate,
        "mode_manifest_sha256": capture.mode_manifest_sha256,
        "image_approvals": [
            {
                "candidate": candidate,
                "image_path": image.path,
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
    path = root.parent / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return root, path, request


def _command(root: Path, request: Path) -> list[str]:
    return [
        "check-plugin-presentation",
        str(root),
        "--source-revision",
        REVISION,
        "--request",
        str(request),
        "--json",
        "--robot",
    ]


def test_actual_cli_accept_reject_recover(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, path, request = _fixture(tmp_path)
    command = _command(root, path)
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "plugin-presentation-check/v1" and result["status"] == "pass"
    assert not result["release_ready"] and not result["host_display_observed"]
    request["copy_approval"]["accurate"] = False
    path.write_text(json.dumps(request), encoding="utf-8")
    assert main(command) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    request["copy_approval"]["accurate"] = True
    path.write_text(json.dumps(request), encoding="utf-8")
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


@pytest.mark.parametrize("change", ["bytes", "mode"])
def test_retained_approval_rejects_valid_source_drift_and_recovers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    root, path, retained = _fixture(tmp_path)
    image = root / "assets" / "icon.svg"
    original, mode = image.read_bytes(), image.stat().st_mode
    assert main(_command(root, path)) == 0
    capsys.readouterr()
    if change == "bytes":
        image.write_bytes(original.replace(b"<rect ", b'<rect fill="#000" '))
    else:
        image.chmod(mode ^ 0o100)
    capture = validate_plugin_package(root, source_revision=REVISION)
    assert capture.status == "pass"
    assert main(_command(root, path)) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["findings"][0]["code"] == "plugin_presentation_binding_mismatch"
    assert blocked["candidate"] == capture.candidate.model_dump(mode="json")
    renewed = json.loads(json.dumps(retained))
    candidate = capture.candidate.model_dump(mode="json")
    renewed["candidate"] = candidate
    renewed["mode_manifest_sha256"] = capture.mode_manifest_sha256
    renewed["copy_approval"]["candidate"] = candidate
    for approval in renewed["image_approvals"]:
        approval["candidate"] = candidate
        approval["image_sha256"] = next(item.sha256 for item in capture.files if item.path == approval["image_path"])
    path.write_text(json.dumps(renewed), encoding="utf-8")
    assert main(_command(root, path)) == 0
    recovered = json.loads(capsys.readouterr().out)
    assert not recovered["release_ready"] and not recovered["host_display_observed"]
    image.write_bytes(original)
    image.chmod(mode)
    path.write_text(json.dumps(retained), encoding="utf-8")
    assert main(_command(root, path)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


@pytest.mark.parametrize("field", ["package_id", "source_revision", "content_sha256"])
def test_padded_request_identity_is_typed_and_recovers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: str
) -> None:
    root, path, request = _fixture(tmp_path)
    canonical = path.read_bytes()
    request["candidate"][field] = " " + request["candidate"][field] + " "
    path.write_text(json.dumps(request), encoding="utf-8")
    assert main(_command(root, path)) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["candidate"] is None
    assert result["findings"][0]["code"] == "plugin_presentation_input_invalid"
    path.write_bytes(canonical)
    assert main(_command(root, path)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


@pytest.mark.parametrize("kind", ["duplicate", "malformed", "oversized", "symlink"])
def test_bad_external_request_blocks_and_recovers(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    root, path, request = _fixture(tmp_path)
    if kind == "duplicate":
        path.write_text('{"candidate":{},"candidate":{}}', encoding="utf-8")
    elif kind == "malformed":
        path.write_text("{", encoding="utf-8")
    elif kind == "oversized":
        path.write_bytes(b" " * (1024 * 1024 + 1))
    else:
        original = path.with_name("ordinary-request.json")
        path.rename(original)
        path.symlink_to(original.name)
    assert main(_command(root, path)) == 2
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["findings"][0]["code"] == "plugin_presentation_input_invalid"
    if kind == "symlink":
        path.unlink()
    path.write_text(json.dumps(request), encoding="utf-8")
    assert main(_command(root, path)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


def test_help_needs_no_optional_decoder(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    original = builtins.__import__

    def unavailable(name: str, *args: object, **kwargs: object) -> object:
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("optional images extra unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    for command in (["--help"], ["check-plugin-presentation", "--help"]):
        with pytest.raises(SystemExit) as stopped:
            main(command)
        assert stopped.value.code == 0
        assert "check-plugin-presentation" in capsys.readouterr().out
