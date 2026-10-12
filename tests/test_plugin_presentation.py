"""Candidate-bound presentation service, rejection and corrected recovery."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI
from skills_sdk.models.plugin_presentation import PluginPresentationRequest
from skills_sdk.validation import plugin_presentation as service
from skills_sdk.validation.plugin_package import validate_plugin_package
from skills_sdk.validation.plugin_presentation import check_plugin_presentation

REVISION = "1" * 40
PRIVATE_COPY = "Synthetic PRIVATE-COPY-DO-NOT-ECHO description."


def _image(path: Path, size: tuple[int, int] = (48, 48)) -> None:
    stream = io.BytesIO()
    Image.new("RGBA", size, (20, 60, 90, 255)).save(stream, format="PNG")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stream.getvalue())


def _manifest(root: Path, interface: dict[str, object], *, inline: bool = True) -> None:
    settings = {"interface": {key: value for key, value in interface.items() if key != "onboardingSkill"}}
    if "onboardingSkill" in interface:
        settings["onboardingSkill"] = interface["onboardingSkill"]
    payload: dict[str, object] = {"$schema": PLUGIN_SCHEMA_URI, "name": "presentation-fixture"}
    if inline:
        payload["extensions"] = {"com.openai": settings}
    else:
        overlay = root / ".codex-plugin" / "plugin.json"
        overlay.parent.mkdir(exist_ok=True)
        overlay.write_text(json.dumps(settings), encoding="utf-8")
    (root / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path.resolve() / "plugin"
    root.mkdir()
    _image(root / "assets" / "icon.png")
    child = root / "skills" / "fixture-skill"
    child.mkdir(parents=True)
    (child / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: Inspect synthetic examples.\n---\n# Example\n", encoding="utf-8"
    )
    interface: dict[str, object] = {
        "logo": "./assets/icon.png",
        "composerIcon": "./assets/icon.png",
        "description": PRIVATE_COPY,
    }
    _manifest(root, interface)
    return root, interface


def _request(root: Path, *, image_path: str = "assets/icon.png") -> dict[str, object]:
    capture = validate_plugin_package(root, source_revision=REVISION)
    assert capture.status == "pass", capture.model_dump(mode="json")
    assert capture.candidate is not None and capture.manifest is not None
    candidate = capture.candidate.model_dump(mode="json")
    approval = {
        "schema_version": "plugin-image-approval/v1",
        "candidate": candidate,
        "image_path": image_path,
        "image_sha256": hashlib.sha256((root / image_path).read_bytes()).hexdigest(),
        "kind": "icon",
        "professional": True,
        "rights_confirmed": True,
        "recognisable": True,
        "small_size": True,
        "light_dark": True,
        "distinctive": True,
        "evidence_ref": "review-logo",
        "evidence_sha256": "a" * 64,
    }
    return {
        "schema_version": "plugin-presentation-request/v1",
        "candidate": candidate,
        "mode_manifest_sha256": capture.mode_manifest_sha256,
        "image_approvals": [approval],
        "copy_approval": {
            "schema_version": "plugin-presentation-copy-approval/v1",
            "candidate": candidate,
            "openai_settings_sha256": capture.manifest.openai_settings_sha256,
            "accurate": True,
            "evidence_ref": "review-copy",
            "evidence_sha256": "b" * 64,
        },
    }


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _pass(root: Path, request: object) -> object:
    before = _snapshot(root)
    result = check_plugin_presentation(root, source_revision=REVISION, request=request)
    assert result.status == "pass", result.model_dump(mode="json")
    payload = result.model_dump(mode="json")
    assert not payload["mutation_performed"] and not payload["execution_authorized"] and not payload["release_ready"]
    assert PRIVATE_COPY not in json.dumps(payload)
    assert _snapshot(root) == before
    paths = tuple(image.path for image in result.images)
    assert paths == tuple(sorted(set(paths)))
    assert all(image.roles == tuple(sorted(set(image.roles))) for image in result.images)
    return result


@pytest.mark.parametrize("field", ["package_id", "source_revision", "content_sha256"])
@pytest.mark.parametrize("typed", [False, True])
def test_padded_request_identity_blocks_and_recovers(tmp_path: Path, field: str, typed: bool) -> None:
    root, _ = _fixture(tmp_path)
    request = _request(root)
    if typed:
        request = PluginPresentationRequest.model_validate(request)
        candidate = request.candidate.model_copy(update={field: " " + getattr(request.candidate, field) + " "})
        request = request.model_copy(update={"candidate": candidate})
    else:
        request["candidate"][field] = " " + request["candidate"][field] + " "
    result = check_plugin_presentation(root, source_revision=REVISION, request=request)
    assert result.status == "blocked"
    assert result.candidate is None
    assert result.findings[0].code == "plugin_presentation_input_invalid"
    _pass(root, _request(root))


@pytest.mark.parametrize("typed", [False, True])
def test_shared_icon_json_and_typed_acceptance(tmp_path: Path, typed: bool) -> None:
    root, _ = _fixture(tmp_path)
    request = _request(root)
    if typed:
        request = PluginPresentationRequest.model_validate(request)
    result = _pass(root, request)
    assert len(result.images) == 1
    assert result.images[0].path == "assets/icon.png"
    assert result.images[0].sha256 == hashlib.sha256((root / "assets/icon.png").read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "kind",
    [
        "candidate",
        "mode",
        "copy_digest",
        "copy_false",
        "image_hash",
        "duplicate",
        "extra",
        "missing",
        "false",
        "revision",
    ],
)
def test_request_binding_rejection_and_recovery(tmp_path: Path, kind: str) -> None:
    root, _ = _fixture(tmp_path)
    valid = _request(root)
    forged = copy.deepcopy(valid)
    revision = REVISION
    if kind == "candidate":
        forged["candidate"]["content_sha256"] = "0" * 64
    elif kind == "mode":
        forged["mode_manifest_sha256"] = "0" * 64
    elif kind == "copy_digest":
        forged["copy_approval"]["openai_settings_sha256"] = "0" * 64
    elif kind == "copy_false":
        forged["copy_approval"]["accurate"] = False
    elif kind == "image_hash":
        forged["image_approvals"][0]["image_sha256"] = "0" * 64
    elif kind == "duplicate":
        forged["image_approvals"] *= 2
    elif kind == "extra":
        forged["unexpected"] = True
    elif kind == "missing":
        forged["image_approvals"] = []
    elif kind == "false":
        forged["image_approvals"][0]["professional"] = False
    else:
        revision = "2" * 40
    before = _snapshot(root)
    result = check_plugin_presentation(root, source_revision=revision, request=forged)
    assert result.status == "blocked" and result.findings
    assert PRIVATE_COPY not in json.dumps(result.model_dump(mode="json"))
    assert _snapshot(root) == before
    _pass(root, valid)


@pytest.mark.parametrize("criterion", ["rights_confirmed", "recognisable", "small_size", "light_dark", "distinctive"])
def test_visual_criteria_rejection_and_recovery(tmp_path: Path, criterion: str) -> None:
    root, _ = _fixture(tmp_path)
    request = _request(root)
    request["image_approvals"][0][criterion] = False
    assert check_plugin_presentation(root, source_revision=REVISION, request=request).status == "blocked"
    _pass(root, _request(root))


@pytest.mark.parametrize("inline", [False, True])
def test_inline_and_fallback_settings(tmp_path: Path, inline: bool) -> None:
    root, interface = _fixture(tmp_path)
    _manifest(root, interface, inline=inline)
    if inline:
        overlay = root / ".codex-plugin" / "plugin.json"
        overlay.parent.mkdir()
        overlay.write_text("malformed ignored fallback", encoding="utf-8")
    _pass(root, _request(root))


@pytest.mark.parametrize("field", ["logo", "composerIcon"])
def test_required_icon_reference_recovery(tmp_path: Path, field: str) -> None:
    root, interface = _fixture(tmp_path)
    original = interface.pop(field)
    _manifest(root, interface)
    request = _request(root)
    assert check_plugin_presentation(root, source_revision=REVISION, request=request).status == "blocked"
    interface[field] = original
    _manifest(root, interface)
    _pass(root, _request(root))


@pytest.mark.parametrize("field", ["logoDark", "composerIconDark", "screenshots"])
def test_optional_image_metadata_types(tmp_path: Path, field: str) -> None:
    root, interface = _fixture(tmp_path)
    interface[field] = 42
    _manifest(root, interface)
    assert check_plugin_presentation(root, source_revision=REVISION, request=_request(root)).status == "blocked"
    del interface[field]
    _manifest(root, interface)
    _pass(root, _request(root))


def test_valid_dark_variants_share_the_same_approval(tmp_path: Path) -> None:
    root, interface = _fixture(tmp_path)
    interface.update(logoDark="./assets/icon.png", composerIconDark="./assets/icon.png")
    _manifest(root, interface)
    result = _pass(root, _request(root))
    assert len(result.images) == 1 and len(result.images[0].roles) == 4


@pytest.mark.parametrize("reference", ["../icon.png", "./../icon.png", "/absolute/icon.png", "./assets/missing.png"])
def test_unsafe_or_missing_image_reference(tmp_path: Path, reference: str) -> None:
    root, interface = _fixture(tmp_path)
    interface["logo"] = reference
    _manifest(root, interface)
    result = check_plugin_presentation(root, source_revision=REVISION, request=_request(root))
    assert result.status == "blocked" and result.findings
    interface["logo"] = "./assets/icon.png"
    _manifest(root, interface)
    _pass(root, _request(root))


def test_symlink_image_rejection_and_recovery(tmp_path: Path) -> None:
    root, interface = _fixture(tmp_path)
    request = _request(root)
    linked = root / "assets" / "alias.png"
    linked.symlink_to("icon.png")
    interface["logo"] = "./assets/alias.png"
    _manifest(root, interface)
    assert check_plugin_presentation(root, source_revision=REVISION, request=request).status == "blocked"
    linked.unlink()
    interface["logo"] = "./assets/icon.png"
    _manifest(root, interface)
    _pass(root, _request(root))


@pytest.mark.parametrize("kind", ["corrupt", "wrong_extension", "nonsquare", "too_small"])
def test_actual_image_content_rejection_and_recovery(tmp_path: Path, kind: str) -> None:
    root, _ = _fixture(tmp_path)
    path = root / "assets" / "icon.png"
    original = path.read_bytes()
    if kind == "corrupt":
        path.write_bytes(b"not an image")
    elif kind == "wrong_extension":
        stream = io.BytesIO()
        Image.new("RGB", (48, 48)).save(stream, format="JPEG")
        path.write_bytes(stream.getvalue())
    else:
        _image(path, (96, 48) if kind == "nonsquare" else (16, 16))
    assert check_plugin_presentation(root, source_revision=REVISION, request=_request(root)).status == "blocked"
    path.write_bytes(original)
    _pass(root, _request(root))


@pytest.mark.parametrize(
    "reference", ["./skills/fixture-skill/SKILL.md", "./skills/fixture-skill/README.md", "../SKILL.md"]
)
def test_onboarding_requires_discovered_skill_entrypoint(tmp_path: Path, reference: str) -> None:
    root, interface = _fixture(tmp_path)
    interface["onboardingSkill"] = reference
    _manifest(root, interface)
    result = check_plugin_presentation(root, source_revision=REVISION, request=_request(root))
    assert result.status == ("pass" if reference == "./skills/fixture-skill/SKILL.md" else "blocked")
    del interface["onboardingSkill"]
    _manifest(root, interface)
    _pass(root, _request(root))


def test_landscape_screenshot_and_sorted_unique_images(tmp_path: Path) -> None:
    root, interface = _fixture(tmp_path)
    _image(root / "assets" / "screen.png", (96, 48))
    interface["screenshots"] = ["./assets/screen.png"]
    _manifest(root, interface)
    request = _request(root)
    approval = copy.deepcopy(request["image_approvals"][0])
    approval.update(
        image_path="assets/screen.png",
        image_sha256=hashlib.sha256((root / "assets" / "screen.png").read_bytes()).hexdigest(),
        kind="screenshot",
        evidence_ref="review-screenshot",
    )
    for criterion in ("recognisable", "small_size", "light_dark", "distinctive"):
        del approval[criterion]
    request["image_approvals"].append(approval)
    result = _pass(root, request)
    assert tuple(image.path for image in result.images) == ("assets/icon.png", "assets/screen.png")


@pytest.mark.parametrize(
    "content",
    [
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><script>bad()</script></svg>',
        '<!DOCTYPE svg [<!ENTITY e SYSTEM "file:///secret">]><svg width="48" height="48">&e;</svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><image href="https://invalid.example/image"/></svg>',
    ],
)
def test_unsafe_svg_rejection_and_recovery(tmp_path: Path, content: str) -> None:
    root, interface = _fixture(tmp_path)
    (root / "assets" / "icon.svg").write_text(content, encoding="utf-8")
    interface.update(logo="./assets/icon.svg", composerIcon="./assets/icon.svg")
    _manifest(root, interface)
    request = _request(root, image_path="assets/icon.svg")
    assert check_plugin_presentation(root, source_revision=REVISION, request=request).status == "blocked"
    interface.update(logo="./assets/icon.png", composerIcon="./assets/icon.png")
    _manifest(root, interface)
    _pass(root, _request(root))


@pytest.mark.parametrize("phase", ["before_capture", "after_capture"])
@pytest.mark.parametrize("change", ["mode", "bytes"])
def test_source_changes_during_inspection_block_and_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, change: str
) -> None:
    root, _ = _fixture(tmp_path)
    request = _request(root)
    path = root / "assets" / "icon.png"
    payload, mode = path.read_bytes(), path.stat().st_mode & 0o777
    original = service.capture_plugin_source
    calls = 0

    def mutate() -> None:
        if change == "mode":
            path.chmod(mode ^ 0o100)
        else:
            _image(path, (64, 64))

    def capture(source: Path) -> tuple:
        nonlocal calls
        calls += 1
        if calls == 1 and phase == "before_capture":
            mutate()
        result = original(source)
        if calls == 1 and phase == "after_capture":
            mutate()
        return result

    with monkeypatch.context() as patched:
        patched.setattr(service, "capture_plugin_source", capture)
        result = check_plugin_presentation(root, source_revision=REVISION, request=request)
    assert result.status == "blocked"
    assert result.candidate is None
    assert result.findings[0].code == "plugin_source_changed"
    path.write_bytes(payload)
    path.chmod(mode)
    _pass(root, request)


def test_shared_icon_screenshot_uses_stricter_icon_approval(tmp_path: Path) -> None:
    root, interface = _fixture(tmp_path)
    interface["screenshots"] = ["./assets/icon.png"]
    _manifest(root, interface)
    result = _pass(root, _request(root))
    assert result.images[0].roles == ("composerIcon", "logo", "screenshot")
    assert result.images[0].approval.kind == "icon"


def test_shared_svg_screenshot_blocks_and_raster_recovers(tmp_path: Path) -> None:
    root, interface = _fixture(tmp_path)
    (root / "assets" / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><path d="M0 0h48v48H0z"/></svg>',
        encoding="utf-8",
    )
    interface.update(logo="./assets/icon.svg", composerIcon="./assets/icon.svg", screenshots=["./assets/icon.svg"])
    _manifest(root, interface)
    before = _snapshot(root)
    result = check_plugin_presentation(
        root, source_revision=REVISION, request=_request(root, image_path="assets/icon.svg")
    )
    assert result.status == "blocked"
    assert result.findings[0].code == "plugin_presentation_images_invalid"
    assert _snapshot(root) == before
    interface.update(logo="./assets/icon.png", composerIcon="./assets/icon.png", screenshots=["./assets/icon.png"])
    _manifest(root, interface)
    recovered = _pass(root, _request(root))
    assert recovered.images[0].roles == ("composerIcon", "logo", "screenshot")
