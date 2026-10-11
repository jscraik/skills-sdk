"""Supplied envelopes need fresh source verification before metadata reliance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI, PluginPackageValidation, PluginValidationPolicy
from skills_sdk.validation import plugin_evidence as evidence_service
from skills_sdk.validation.plugin_evidence import verify_plugin_package_validation
from skills_sdk.validation.plugin_package import validate_plugin_package

REVISION = "1" * 40


def _fixture(tmp_path: Path) -> tuple[Path, PluginPackageValidation]:
    """Create a plugin with inline and fallback settings and return its passing validation."""
    root = tmp_path.resolve() / "source"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": PLUGIN_SCHEMA_URI,
                "name": "fixture-plugin",
                "version": "1.0.0",
                "description": "Fixture.",
                "extensions": {"com.openai": {"opaque": "never echo these selected values"}},
            }
        ),
        encoding="utf-8",
    )
    compatibility = root / ".codex-plugin" / "plugin.json"
    compatibility.parent.mkdir()
    compatibility.write_text('{"fallback": true}', encoding="utf-8")
    result = validate_plugin_package(root, source_revision=REVISION)
    assert result.status == "pass"
    return root, result


def _code(result: PluginPackageValidation) -> str:
    """Assert an empty blocked capture without authority and return its first finding code."""
    assert result.status == "blocked"
    assert result.candidate is None and not result.files and not result.skills
    assert not result.execution_authorized and not result.release_ready and not result.mutation_performed
    return result.findings[0].code


POLICIES = (
    PluginValidationPolicy(require_version=True),
    PluginValidationPolicy(require_description=True),
    PluginValidationPolicy(require_version=True, require_description=True),
)


@pytest.mark.parametrize(
    "field,value",
    [
        ("openai_settings_sha256", "0" * 64),
        ("version", "2.0.0"),
        ("description", "Invented description"),
        ("openai_settings_source", "compatibility"),
    ],
)
def test_structural_projection_tamper_needs_source_rejection(tmp_path: Path, field: str, value: str) -> None:
    """Verify fresh source rejects altered metadata that passes structural envelope checks."""
    root, good = _fixture(tmp_path)
    raw = good.model_dump(mode="json")
    raw["manifest"][field] = value
    envelope = PluginPackageValidation.model_validate(raw)
    SchemaRegistry().validate("plugin-package-validation.v1", raw)
    assert envelope.candidate == good.candidate
    rejected = verify_plugin_package_validation(root, raw, source_revision=REVISION)
    assert _code(rejected) == "plugin_evidence_mismatch"
    copied = good.model_copy(update={"manifest": good.manifest.model_copy(update={field: value})})
    assert _code(verify_plugin_package_validation(root, copied, source_revision=REVISION)) == "plugin_evidence_mismatch"
    assert verify_plugin_package_validation(root, good, source_revision=REVISION) == good
    assert "never echo these selected values" not in rejected.model_dump_json()


def test_invalid_raw_and_nested_copied_inputs_fail_before_source(tmp_path: Path) -> None:
    """Verify malformed, forged and cyclic envelopes yield invalid-evidence blockers."""
    root, good = _fixture(tmp_path)
    malformed = good.model_copy(update={"manifest": good.manifest.model_copy(update={"undeclared": True})})
    for invalid in ({}, malformed, good.model_copy(update={"release_ready": True})):
        assert (
            _code(verify_plugin_package_validation(root, invalid, source_revision=REVISION))
            == "plugin_evidence_invalid"
        )
    raw = good.model_dump(mode="json")
    raw["manifest"]["name"] = "different-name"
    assert _code(verify_plugin_package_validation(root, raw, source_revision=REVISION)) == "plugin_evidence_invalid"
    cyclic: dict[str, object] = {}
    cyclic["cycle"] = cyclic
    assert _code(verify_plugin_package_validation(root, cyclic, source_revision=REVISION)) == "plugin_evidence_invalid"
    assert verify_plugin_package_validation(root, good.model_dump(mode="json"), source_revision=REVISION) == good


@pytest.mark.parametrize("policy", POLICIES)
def test_explicit_policy_survives_invalid_mismatch_and_recovery(tmp_path: Path, policy: PluginValidationPolicy) -> None:
    """Retain caller policy through rejected evidence and corrected-input recovery."""
    root, good = _fixture(tmp_path)
    strict = validate_plugin_package(root, source_revision=REVISION, policy=policy)
    assert strict.status == "pass" and strict.policy == policy
    invalid_inputs = (
        {},
        good.model_copy(update={"release_ready": True}),
    )
    for invalid in invalid_inputs:
        rejected = verify_plugin_package_validation(root, invalid, source_revision=REVISION, policy=policy)
        assert _code(rejected) == "plugin_evidence_invalid"
        assert rejected.policy == policy
    forged = strict.model_dump(mode="json")
    forged["manifest"]["openai_settings_sha256"] = "0" * 64
    mismatch = verify_plugin_package_validation(root, forged, source_revision=REVISION, policy=policy)
    assert _code(mismatch) == "plugin_evidence_mismatch"
    assert mismatch.policy == policy
    recovered = verify_plugin_package_validation(root, strict, source_revision=REVISION, policy=policy)
    assert recovered == strict and recovered.policy == policy
    assert not recovered.execution_authorized and not recovered.release_ready and not recovered.mutation_performed


@pytest.mark.parametrize(
    "policy",
    [
        {"require_version": 1},
        {"require_description": "true"},
        {"require_version": False, "unknown": True},
        PluginValidationPolicy().model_copy(update={"require_version": 1}),
    ],
)
def test_invalid_policy_fails_before_source_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy: object
) -> None:
    """Reject malformed or copied policies before any source validation call."""
    root, good = _fixture(tmp_path)

    def source_access(*args: object, **kwargs: object) -> PluginPackageValidation:
        """Fail if invalid policy reaches the source reader."""
        raise AssertionError("invalid caller policy reached source validation")

    monkeypatch.setattr(evidence_service, "validate_plugin_package", source_access)
    rejected = verify_plugin_package_validation(root, good, source_revision=REVISION, policy=policy)
    assert _code(rejected) == "plugin_input_invalid"
    assert rejected.policy == PluginValidationPolicy()
    assert not rejected.execution_authorized and not rejected.release_ready and not rejected.mutation_performed


def test_revision_and_policy_are_caller_explicit(tmp_path: Path) -> None:
    """Require supplied evidence to match the caller-selected revision and metadata policy."""
    root, good = _fixture(tmp_path)
    assert _code(verify_plugin_package_validation(root, good, source_revision="2" * 40)) == "plugin_evidence_mismatch"
    policy = PluginValidationPolicy(require_version=True, require_description=True)
    strict = validate_plugin_package(root, source_revision=REVISION, policy=policy)
    assert strict.status == "pass"
    assert _code(verify_plugin_package_validation(root, strict, source_revision=REVISION)) == "plugin_evidence_mismatch"
    assert verify_plugin_package_validation(root, strict, source_revision=REVISION, policy=policy) == strict
    (root / "plugin.json").write_text(
        json.dumps({"$schema": PLUGIN_SCHEMA_URI, "name": "fixture-plugin"}), encoding="utf-8"
    )
    result = verify_plugin_package_validation(root, good, source_revision=REVISION, policy=policy)
    assert result.status == "blocked" and "sdk_plugin_version_required" in {item.code for item in result.findings}


def test_source_change_malformed_and_symlink_recover(tmp_path: Path) -> None:
    """Reject changed, malformed or symlinked source and accept the restored original."""
    root, good = _fixture(tmp_path)
    manifest = root / "plugin.json"
    original = manifest.read_bytes()
    manifest.write_bytes(original + b"\n")
    assert _code(verify_plugin_package_validation(root, good, source_revision=REVISION)) == "plugin_evidence_mismatch"
    manifest.write_bytes(b"{}")
    assert verify_plugin_package_validation(root, good, source_revision=REVISION).status == "blocked"
    manifest.write_bytes(original)
    alias = root.parent / "alias"
    alias.symlink_to(root, target_is_directory=True)
    assert verify_plugin_package_validation(alias, good, source_revision=REVISION).status == "blocked"
    assert verify_plugin_package_validation(root, good, source_revision=REVISION) == good


@pytest.mark.parametrize("inline", [{}, False])
def test_selection_and_unused_overlay_bound_without_echo(tmp_path: Path, inline: object) -> None:
    """Verify settings selection and retained overlay bytes without exposing raw settings."""
    root, _ = _fixture(tmp_path)
    manifest = root / "plugin.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    metadata["extensions"]["com.openai"] = inline
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    if isinstance(inline, dict):
        (root / ".codex-plugin" / "plugin.json").write_text("malformed unused fallback", encoding="utf-8")
    good = validate_plugin_package(root, source_revision=REVISION)
    assert good.status == "pass"
    assert good.manifest.openai_settings_source == ("inline" if isinstance(inline, dict) else "compatibility")
    assert verify_plugin_package_validation(root, good, source_revision=REVISION) == good
    assert "malformed unused fallback" not in good.model_dump_json()


@pytest.mark.parametrize("source", ["inline", "compatibility"])
def test_nested_selected_settings_are_hash_bound_without_raw_retention(tmp_path: Path, source: str) -> None:
    """Verify nested settings are represented by a digest and reject forged or raw settings evidence."""
    root, _ = _fixture(tmp_path)
    manifest = root / "plugin.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    settings = {"nested": [None, 1.5, {"execution_authorized": True}], "opaque": "SYNTHETIC-PRIVATE-VALUE"}
    metadata["extensions"]["com.openai"] = settings if source == "inline" else False
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    (root / ".codex-plugin" / "plugin.json").write_text(json.dumps(settings), encoding="utf-8")
    good = validate_plugin_package(root, source_revision=REVISION)
    assert good.status == "pass" and good.manifest is not None
    assert good.manifest.openai_settings_source == source
    assert good.manifest.openai_settings_sha256 == canonical_json_sha256(settings)
    assert "openai_settings" not in good.manifest.model_dump(mode="json")
    assert "SYNTHETIC-PRIVATE-VALUE" not in good.model_dump_json()
    assert not good.execution_authorized
    SchemaRegistry().validate("plugin-package-validation.v1", good.model_dump(mode="json"))
    forged = good.model_dump(mode="json")
    forged["manifest"]["openai_settings_sha256"] = "0" * 64
    assert _code(verify_plugin_package_validation(root, forged, source_revision=REVISION)) == "plugin_evidence_mismatch"
    forged["manifest"]["openai_settings"] = settings
    assert _code(verify_plugin_package_validation(root, forged, source_revision=REVISION)) == "plugin_evidence_invalid"
    assert verify_plugin_package_validation(root, good, source_revision=REVISION) == good


def test_no_selected_settings_rejects_orphan_digest(tmp_path: Path) -> None:
    """Reject an orphan settings digest across model, registry and source verification boundaries."""
    root, _ = _fixture(tmp_path)
    manifest = root / "plugin.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    del metadata["extensions"]
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    (root / ".codex-plugin" / "plugin.json").unlink()
    good = validate_plugin_package(root, source_revision=REVISION)
    assert good.status == "pass" and good.manifest is not None
    assert good.manifest.openai_settings_source == "none"
    assert good.manifest.openai_settings_sha256 is None
    raw = good.model_dump(mode="json")
    raw["manifest"]["openai_settings_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(raw)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-package-validation.v1", raw)
    assert _code(verify_plugin_package_validation(root, raw, source_revision=REVISION)) == "plugin_evidence_invalid"
    SchemaRegistry().validate("plugin-package-validation.v1", good.model_dump(mode="json"))
    assert verify_plugin_package_validation(root, good, source_revision=REVISION) == good
