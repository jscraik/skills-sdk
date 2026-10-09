"""Portable whole-plugin intake, closure and corrected-input recovery."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from skills_sdk.cli.main import main
from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.plugin import (
    PLUGIN_SCHEMA_URI,
    PluginCapturedFile,
    PluginPackageValidation,
    PluginValidationPolicy,
)
from skills_sdk.validation import plugin_capture
from skills_sdk.validation import plugin_package as service
from skills_sdk.validation.plugin_package import validate_plugin_package
from skills_sdk.validation.skill_package import validate_skill_package

REVISION = "1" * 40


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    """Create a plugin containing one skill and an asset, returning its root and metadata."""
    root = tmp_path.resolve() / "arbitrary-source-directory"
    child = root / "skills" / "fixture-skill"
    child.mkdir(parents=True)
    (child / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: Inspect synthetic examples.\n---\n# Example\n", encoding="utf-8"
    )
    (root / "assets").mkdir()
    (root / "assets" / "icon.txt").write_text("Synthetic icon\n", encoding="utf-8")
    payload: dict[str, object] = {"$schema": PLUGIN_SCHEMA_URI, "name": "fixture-.plugin"}
    _manifest(root, payload)
    return root, payload


def _manifest(root: Path, payload: dict[str, object]) -> None:
    """Write the supplied metadata as the root plugin.json fixture."""
    (root / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")


def _valid(root: Path) -> PluginPackageValidation:
    """Validate the fixture at the fixed revision and assert a passing result."""
    result = validate_plugin_package(root, source_revision=REVISION)
    assert result.status == "pass", result.model_dump(mode="json")
    return result


def _reject(value: object) -> None:
    """Assert that the plugin validation model rejects the supplied envelope."""
    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(value)


def test_complete_capture_schema_and_standalone_compatibility(tmp_path: Path) -> None:
    """Verify complete capture, schema acceptance and equivalence to standalone child validation."""
    root, _ = _fixture(tmp_path)
    result = _valid(root)
    assert result.candidate is not None and result.manifest is not None
    assert result.candidate.package_id == "plugin-" + hashlib.sha256(b"fixture-.plugin").hexdigest()
    assert result.manifest.version is None and result.manifest.description is None
    assert {item.path for item in result.files} == {"plugin.json", "assets/icon.txt", "skills/fixture-skill/SKILL.md"}
    assert not result.mutation_performed and not result.execution_authorized and not result.release_ready
    SchemaRegistry().validate("plugin-package-validation.v1", result.model_dump(mode="json"))
    assert PluginPackageValidation.model_validate(result) == result
    standalone = validate_skill_package(root / "skills" / "fixture-skill", source_revision=REVISION)
    assert result.skills[0].validation == standalone


def test_optional_metadata_and_explicit_release_policy_recovery(tmp_path: Path) -> None:
    """Require optional metadata only under explicit policy and accept corrected input."""
    root, payload = _fixture(tmp_path)
    _valid(root)
    policy = PluginValidationPolicy(require_version=True, require_description=True)
    rejected = validate_plugin_package(root, source_revision=REVISION, policy=policy)
    assert rejected.status == "blocked"
    assert {item.code for item in rejected.findings} == {
        "sdk_plugin_version_required",
        "sdk_plugin_description_required",
    }
    payload.update(version="1.0.0", description="Synthetic release fixture.")
    _manifest(root, payload)
    recovered = validate_plugin_package(root, source_revision=REVISION, policy=policy)
    assert recovered.status == "pass" and recovered.policy == policy


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"[]",
        b"\xff",
        b'{"$schema":"wrong","name":"fixture"}',
        b'{"$schema":"' + PLUGIN_SCHEMA_URI.encode() + b'","name":"fixture","name":"other"}',
        b'{"$schema":"' + PLUGIN_SCHEMA_URI.encode() + b'","name":"fixture","unknown":NaN}',
        b"[" * 1000 + b"0" + b"]" * 1000,
    ],
)
def test_malformed_root_rejection_and_recovery(tmp_path: Path, payload: bytes) -> None:
    """Block malformed root manifests and accept restored valid metadata."""
    root, metadata = _fixture(tmp_path)
    (root / "plugin.json").write_bytes(payload)
    result = validate_plugin_package(root, source_revision=REVISION)
    assert result.status == "blocked" and result.findings[0].code == "plugin_input_invalid"
    _manifest(root, metadata)
    _valid(root)


def test_unknown_metadata_extensions_and_mcp_are_not_clearance(tmp_path: Path) -> None:
    """Verify ignored metadata and unassessed MCP content produce warnings without authority."""
    root, metadata = _fixture(tmp_path)
    metadata.update(unknown={"ignored": True}, extensions="not-an-object")
    _manifest(root, metadata)
    (root / "mcp.json").write_text("not configuration proof", encoding="utf-8")
    result = _valid(root)
    assert {item.code for item in result.findings} == {
        "plugin_unknown_fields_ignored",
        "plugin_extensions_ignored",
        "plugin_mcp_not_assessed",
    }
    assert result.manifest is not None and result.manifest.openai_settings_source == "none"
    assert not result.execution_authorized and not result.release_ready


def test_openai_selection_replaces_overlay_without_merging(tmp_path: Path) -> None:
    """Verify inline settings replace fallback settings and their digest ignores key order."""
    root, metadata = _fixture(tmp_path)
    overlay = root / ".codex-plugin" / "plugin.json"
    overlay.parent.mkdir()
    fallback = {"fallback": True}
    overlay.write_text(json.dumps(fallback), encoding="utf-8")
    result = _valid(root)
    assert result.manifest is not None
    assert result.manifest.openai_settings_source == "compatibility"
    assert result.manifest.openai_settings_sha256 == canonical_json_sha256(fallback)
    inline = {"notAdapterValidated": {"second": 2, "first": 1}}
    metadata["extensions"] = {"com.openai": inline}
    _manifest(root, metadata)
    overlay.write_text("malformed unused fallback", encoding="utf-8")
    result = _valid(root)
    assert result.manifest is not None and result.manifest.openai_settings_source == "inline"
    assert result.manifest.openai_settings_sha256 == canonical_json_sha256(inline)
    assert not result.execution_authorized
    metadata["extensions"] = {"com.openai": {"notAdapterValidated": {"first": 1, "second": 2}}}
    _manifest(root, metadata)
    assert _valid(root).manifest == result.manifest.model_copy(
        update={
            "source_sha256": hashlib.sha256((root / "plugin.json").read_bytes()).hexdigest(),
        }
    )


def test_immediate_discovery_and_child_recovery(tmp_path: Path) -> None:
    """Discover only direct skills, block invalid child metadata and accept its repair."""
    root, _ = _fixture(tmp_path)
    nested = root / "skills" / "group" / "nested"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("not a discovered skill", encoding="utf-8")
    result = _valid(root)
    assert tuple(item.path for item in result.skills) == ("skills/fixture-skill",)
    skill = root / "skills" / "fixture-skill" / "SKILL.md"
    original = skill.read_bytes()
    skill.write_bytes(original.replace(b"fixture-skill", b"wrong-name"))
    rejected = validate_plugin_package(root, source_revision=REVISION)
    assert rejected.status == "blocked" and "plugin_child_blocked" in {item.code for item in rejected.findings}
    skill.write_bytes(original)
    _valid(root)


@pytest.mark.parametrize(
    "kind", ["missing_child", "child_revision", "child_name", "candidate_id", "mode", "manifest", "authority"]
)
def test_raw_and_copied_nested_forgery_rejected(tmp_path: Path, kind: str) -> None:
    """Reject tampered bindings and authority across raw, copied, constructed and registry inputs."""
    root, _ = _fixture(tmp_path)
    good = _valid(root)
    raw = good.model_dump(mode="json")
    child = good.skills[0]
    if kind == "missing_child":
        raw["skills"] = []
        copied = good.model_copy(update={"skills": ()})
    elif kind == "child_revision":
        raw["skills"][0]["validation"]["candidate"]["source_revision"] = "2" * 40
        candidate = child.validation.candidate.model_copy(update={"source_revision": "2" * 40})
        copied = good.model_copy(
            update={
                "skills": (
                    child.model_copy(
                        update={
                            "validation": child.validation.model_copy(update={"candidate": candidate}),
                        }
                    ),
                )
            }
        )
    elif kind == "child_name":
        raw["skills"][0]["validation"]["identity"]["name"] = "other-skill"
        identity = child.validation.identity.model_copy(update={"name": "other-skill"})
        copied = good.model_copy(
            update={
                "skills": (
                    child.model_copy(
                        update={
                            "validation": child.validation.model_copy(update={"identity": identity}),
                        }
                    ),
                )
            }
        )
    elif kind == "candidate_id":
        raw["candidate"]["package_id"] = "other-plugin"
        copied = good.model_copy(update={"candidate": good.candidate.model_copy(update={"package_id": "other-plugin"})})
    elif kind == "mode":
        raw["files"][0]["permission_mode"] = 0o755
        changed = good.files[0].model_copy(update={"permission_mode": 0o755})
        copied = good.model_copy(update={"files": (changed, *good.files[1:])})
    elif kind == "manifest":
        raw["manifest"]["source_sha256"] = "0" * 64
        copied = good.model_copy(update={"manifest": good.manifest.model_copy(update={"source_sha256": "0" * 64})})
    else:
        raw["execution_authorized"] = True
        copied = good.model_copy(update={"execution_authorized": True})
    _reject(raw)
    _reject(PluginPackageValidation.model_construct(**raw))
    _reject(copied)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-package-validation.v1", raw)
    assert PluginPackageValidation.model_validate(good) == good


def test_extra_copied_members_and_closure_rejected(tmp_path: Path) -> None:
    """Reject extra copied fields, incomplete child files and unsorted capture records."""
    root, _ = _fixture(tmp_path)
    good = _valid(root)
    forged = good.files[0].model_copy(update={"undeclared": True})
    _reject(good.model_copy(update={"files": (forged, *good.files[1:])}))
    child = good.skills[0]
    _reject(
        good.model_copy(
            update={
                "skills": (
                    child.model_copy(
                        update={
                            "validation": child.validation.model_copy(update={"files": ()}),
                        }
                    ),
                )
            }
        )
    )
    _reject(good.model_copy(update={"files": tuple(reversed(good.files))}))
    assert PluginPackageValidation.model_validate(good) == good


def test_ordinary_modes_bound_separately(tmp_path: Path) -> None:
    """Verify permission changes affect the mode digest while preserving the content candidate."""
    root, _ = _fixture(tmp_path)
    before = _valid(root)
    resource = root / "assets" / "icon.txt"
    resource.chmod(0o755)
    after = _valid(root)
    assert before.candidate == after.candidate
    assert before.mode_manifest_sha256 != after.mode_manifest_sha256
    assert next(item for item in after.files if item.path == "assets/icon.txt").permission_mode == 0o755


@pytest.mark.parametrize("kind", ["symlink", "credential", "fifo", "special_mode"])
def test_unsafe_resource_rejection_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """Block unsafe files or modes and accept the plugin after removing the offending resource."""
    root, _ = _fixture(tmp_path)
    resource = root / "assets" / (".env" if kind == "credential" else "unsafe")
    if kind == "symlink":
        resource.symlink_to("icon.txt")
    elif kind == "fifo":
        os.mkfifo(resource)
    else:
        resource.write_text("Synthetic fixture", encoding="utf-8")
        if kind == "special_mode":
            original = plugin_capture._metadata

            def special_metadata(descriptor: int) -> tuple[int, ...]:
                """Simulate a setuid bit on regular files while preserving the remaining descriptor metadata."""
                value = original(descriptor)
                return (*value[:2], value[2] | 0o4000, *value[3:]) if stat.S_ISREG(value[2]) else value

            monkeypatch.setattr(plugin_capture, "_metadata", special_metadata)
    assert validate_plugin_package(root, source_revision=REVISION).status == "blocked"
    monkeypatch.undo()
    resource.unlink()
    _valid(root)


def test_second_capture_observes_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject source changes observed during confirming capture and accept a stable retry."""
    root, _ = _fixture(tmp_path)
    original = service.capture_plugin_source
    calls = 0

    def capture(path: Path) -> tuple[tuple[PluginCapturedFile, ...], dict[str, bytes], tuple[str, ...]]:
        """Change an asset just before the second capture to simulate source drift."""
        nonlocal calls
        calls += 1
        if calls == 2:
            (root / "assets" / "icon.txt").write_text("changed", encoding="utf-8")
        return original(path)

    monkeypatch.setattr(service, "capture_plugin_source", capture)
    rejected = validate_plugin_package(root, source_revision=REVISION)
    assert rejected.status == "blocked" and rejected.findings[0].code == "plugin_source_changed"
    monkeypatch.setattr(service, "capture_plugin_source", original)
    _valid(root)


def test_sparse_oversized_file_blocks_without_unbounded_read(tmp_path: Path) -> None:
    """Reject a sparse file beyond the per-file budget and accept its removal."""
    root, _ = _fixture(tmp_path)
    oversized = root / "assets" / "oversized.bin"
    with oversized.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    assert validate_plugin_package(root, source_revision=REVISION).status == "blocked"
    oversized.unlink()
    _valid(root)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", None),
        ("version", 1),
        ("description", None),
        ("description", []),
        ("homepage", None),
        ("homepage", {}),
        ("repository", None),
        ("repository", 3),
        ("license", None),
        ("license", False),
        ("author", None),
        ("author", "name"),
        ("author", {"name": "Synthetic", "unknown": True}),
        ("author", {"email": []}),
        ("keywords", None),
        ("keywords", "one"),
        ("keywords", ["one", 2]),
    ],
)
def test_known_metadata_wrong_types_reject_and_recover(tmp_path: Path, field: str, value: object) -> None:
    """Block wrongly typed known fields and accept the manifest after removing them."""
    root, payload = _fixture(tmp_path)
    payload[field] = value
    _manifest(root, payload)
    assert validate_plugin_package(root, source_revision=REVISION).status == "blocked"
    del payload[field]
    _manifest(root, payload)
    _valid(root)


@pytest.mark.parametrize("name", ["UPPER", "unicode-é", "two--parts", "two..parts", "-edge", "edge.", ""])
def test_invalid_names_reject_and_recover(tmp_path: Path, name: str) -> None:
    """Reject nonportable plugin names and accept a valid name after correction."""
    root, payload = _fixture(tmp_path)
    payload["name"] = name
    _manifest(root, payload)
    assert validate_plugin_package(root, source_revision=REVISION).status == "blocked"
    payload["name"] = "fixture-.plugin"
    _manifest(root, payload)
    _valid(root)


def test_openai_empty_inline_and_nonobject_fallback_selection(tmp_path: Path) -> None:
    """Verify empty inline settings take precedence and nonobjects trigger validated fallback selection."""
    root, payload = _fixture(tmp_path)
    overlay = root / ".codex-plugin" / "plugin.json"
    overlay.parent.mkdir()
    overlay.write_text("malformed unused fallback", encoding="utf-8")
    payload["extensions"] = {"com.openai": {}, "opaque.namespace": [1, 2]}
    _manifest(root, payload)
    inline = _valid(root).manifest
    assert inline is not None and inline.openai_settings_source == "inline"
    assert inline.openai_settings_sha256 == canonical_json_sha256({})
    fallback = {"opaque": {"nested": True}}
    overlay.write_text(json.dumps(fallback), encoding="utf-8")
    payload["extensions"] = {"com.openai": False, "opaque.namespace": None}
    _manifest(root, payload)
    selected = _valid(root).manifest
    assert selected is not None and selected.openai_settings_source == "compatibility"
    assert selected.openai_settings_sha256 == canonical_json_sha256(fallback)
    overlay.write_text("malformed selected fallback", encoding="utf-8")
    assert validate_plugin_package(root, source_revision=REVISION).status == "blocked"
    overlay.write_text(json.dumps(fallback), encoding="utf-8")
    _valid(root)


def test_invalid_filename_rejects_and_recovers(tmp_path: Path) -> None:
    """Reject a nonportable resource path and accept the plugin after removing it."""
    root, _ = _fixture(tmp_path)
    resource = root / "assets" / "invalid\\path"
    resource.write_bytes(b"synthetic")
    assert validate_plugin_package(root, source_revision=REVISION).status == "blocked"
    resource.unlink()
    _valid(root)


@pytest.mark.parametrize("bound", ["MAX_FILES", "MAX_RESOURCES", "MAX_DEPTH", "MAX_TOTAL_BYTES", "MAX_FILE_BYTES"])
def test_capture_limits_reject_and_recover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
) -> None:
    """Enforce each capture budget and accept the fixture when normal limits are restored."""
    root, _ = _fixture(tmp_path)
    monkeypatch.setattr(plugin_capture, bound, 1)
    assert validate_plugin_package(root, source_revision=REVISION).status == "blocked"
    monkeypatch.undo()
    _valid(root)


def test_cli_policy_rejection_and_recovery(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify CLI metadata policy blockers, corrected-input success and absence of release authority."""
    root, payload = _fixture(tmp_path)
    command = ["validate-plugin", str(root), "--source-revision", REVISION, "--json", "--robot"]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
    policy_command = [*command, "--require-version", "--require-description"]
    assert main(policy_command) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    payload.update(version="1.0.0", description="Synthetic fixture.")
    _manifest(root, payload)
    assert main(policy_command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "pass" and not result["release_ready"]


def test_failed_capture_retains_valid_policy_without_coercing_forged_policy(tmp_path: Path) -> None:
    """Retain valid policy on capture failure and reject copied policy with nonboolean values."""
    root, metadata = _fixture(tmp_path)
    policy = PluginValidationPolicy(require_version=True)
    (root / "plugin.json").write_text("{}", encoding="utf-8")
    rejected = validate_plugin_package(root, source_revision=REVISION, policy=policy)
    assert rejected.status == "blocked" and rejected.policy == policy
    _manifest(root, metadata)
    forged = policy.model_copy(update={"require_version": 1})
    assert validate_plugin_package(root, source_revision=REVISION, policy=forged).status == "blocked"
    _valid(root)


@pytest.mark.parametrize("flag", ["mutation_performed", "execution_authorized", "release_ready"])
def test_authority_flags_cannot_coerce_zero(tmp_path: Path, flag: str) -> None:
    """Reject integer zero in top-level and nested authority flags instead of coercing it to false."""
    root, _ = _fixture(tmp_path)
    value = _valid(root).model_dump(mode="json")
    value[flag] = 0
    _reject(value)
    value[flag] = False
    value["skills"][0]["validation"]["mutation_performed"] = 0
    _reject(value)
