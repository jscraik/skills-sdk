"""Retained plugin evidence must preserve canonical types and component kinds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI, PluginPackageValidation, PluginValidationPolicy
from skills_sdk.validation import validate_plugin_package, verify_plugin_package_validation

REVISION = "1" * 40


def _fixture(tmp_path: Path) -> Path:
    """Create a valid plugin with a one-byte child asset and an empty asset."""
    root = tmp_path.resolve() / "plugin"
    child = root / "skills" / "fixture-skill"
    child.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"$schema": PLUGIN_SCHEMA_URI, "name": "fixture-plugin"}), encoding="utf-8"
    )
    (child / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: Synthetic fixture.\n---\n# Fixture\n", encoding="utf-8"
    )
    (child / "one.txt").write_bytes(b"x")
    (child / "empty.txt").write_bytes(b"")
    return root


@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
@pytest.mark.parametrize("size", ["1", True, "0", False])
def test_child_sizes_cannot_be_coerced(tmp_path: Path, form: str, size: object) -> None:
    """Reject malformed nested sizes without weakening valid typed input or recovery."""
    root = _fixture(tmp_path)
    good = validate_plugin_package(root, source_revision=REVISION)
    assert good.status == "pass"
    binding = good.skills[0]
    filename = "empty.txt" if size in ("0", False) else "one.txt"
    files = tuple(
        item.model_copy(update={"size_bytes": size}) if item.path == filename else item
        for item in binding.validation.files
    )
    child = binding.model_copy(update={"validation": binding.validation.model_copy(update={"files": files})})
    raw = good.model_dump(mode="json")
    for item in raw["skills"][0]["validation"]["files"]:
        if item["path"] == filename:
            item["size_bytes"] = size
    if form == "raw":
        forged = raw
    elif form == "copy":
        forged = good.model_copy(update={"skills": (child,)})
    else:
        forged = PluginPackageValidation.model_construct(**{**good.__dict__, "skills": (child,)})
    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-package-validation.v1", raw)
    rejected = verify_plugin_package_validation(root, forged, source_revision=REVISION)
    assert rejected.status == "blocked" and rejected.findings[0].code == "plugin_evidence_invalid"
    assert verify_plugin_package_validation(root, good, source_revision=REVISION) == good
    SchemaRegistry().validate("plugin-package-validation.v1", good.model_dump(mode="json"))


@pytest.mark.parametrize("component", ["skills", "mcp.json/nested.txt", "skills/fixture-skill/SKILL.md/nested.txt"])
@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
def test_captured_component_kind_cannot_be_cleared(tmp_path: Path, component: str, form: str) -> None:
    """Keep component blockers that are independently proved by retained paths."""
    root = tmp_path.resolve() / "plugin"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"$schema": PLUGIN_SCHEMA_URI, "name": "fixture-plugin"}), encoding="utf-8"
    )
    invalid = root / component
    invalid.parent.mkdir(parents=True, exist_ok=True)
    invalid.write_bytes(b"x")
    blocked = validate_plugin_package(root, source_revision=REVISION)
    assert blocked.status == "blocked" and blocked.candidate is not None
    assert "plugin_component_kind_invalid" in {item.code for item in blocked.findings}
    assert verify_plugin_package_validation(root, blocked, source_revision=REVISION) == blocked
    SchemaRegistry().validate("plugin-package-validation.v1", blocked.model_dump(mode="json"))
    raw = blocked.model_dump(mode="json")
    raw.update(status="pass", findings=[])
    if form == "raw":
        forged = raw
    elif form == "copy":
        forged = blocked.model_copy(update={"status": "pass", "findings": ()})
    else:
        forged = PluginPackageValidation.model_construct(**{**blocked.__dict__, "status": "pass", "findings": ()})
    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-package-validation.v1", raw)
    rejected = verify_plugin_package_validation(root, forged, source_revision=REVISION)
    assert rejected.findings[0].code == "plugin_evidence_invalid"
    invalid.unlink()
    if component != "skills":
        invalid.parent.rmdir()
    recovered = validate_plugin_package(root, source_revision=REVISION)
    assert recovered.status == "pass"
    assert verify_plugin_package_validation(root, recovered, source_revision=REVISION) == recovered


def test_component_kind_requires_the_specific_blocker_and_preserves_neighbours(tmp_path: Path) -> None:
    """A different blocker or a warning cannot hide the proven invalid component kind."""
    root = _fixture(tmp_path)
    nested = root / "mcp.json" / "nested.txt"
    nested.parent.mkdir()
    nested.write_bytes(b"x")
    blocked = validate_plugin_package(root, source_revision=REVISION)
    raw = blocked.model_dump(mode="json")
    raw["findings"][0]["code"] = "unrelated_blocker"
    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(raw)
    warning = blocked.model_dump(mode="json")["findings"][0]
    warning["severity"] = "warning"
    raw["findings"].append(warning)
    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(raw)
    nested.unlink()
    nested.parent.rmdir()
    for name in ("skills.txt", "mcp.json.txt"):
        (root / name).write_bytes(b"ordinary resource")
    recovered = validate_plugin_package(root, source_revision=REVISION)
    assert recovered.status == "pass"
    assert verify_plugin_package_validation(root, recovered, source_revision=REVISION) == recovered


def _forged_result(good: PluginPackageValidation, raw: dict[str, object], form: str) -> object:
    """Preserve raw nested values in each supported untrusted top-level form."""
    if form == "raw":
        return raw
    if form == "copy":
        return good.model_copy(update=raw)
    return PluginPackageValidation.model_construct(**raw)


def _reject_retained(root: Path, good: PluginPackageValidation, raw: dict[str, object], form: str) -> None:
    """Require model, registered schema and verifier rejection plus typed recovery."""
    forged = _forged_result(good, raw, form)
    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-package-validation.v1", raw)
    rejected = verify_plugin_package_validation(root, forged, source_revision=REVISION, policy=good.policy)
    assert rejected.status == "blocked" and rejected.findings[0].code == "plugin_evidence_invalid"
    assert verify_plugin_package_validation(root, good, source_revision=REVISION, policy=good.policy) == good
    SchemaRegistry().validate("plugin-package-validation.v1", good.model_dump(mode="json"))


@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
@pytest.mark.parametrize("child", [False, True])
@pytest.mark.parametrize("field", ["package_id", "source_revision", "content_sha256"])
@pytest.mark.parametrize("padding", [" ", "\t\n"])
def test_padded_candidate_identity_is_not_normalised(
    tmp_path: Path, form: str, child: bool, field: str, padding: str
) -> None:
    """Reject whitespace-padded identities before frozen nested models strip them."""
    root = _fixture(tmp_path)
    good = validate_plugin_package(root, source_revision=REVISION)
    raw = good.model_dump(mode="json")
    candidate = raw["skills"][0]["validation"]["candidate"] if child else raw["candidate"]
    candidate[field] = padding + candidate[field] + padding
    _reject_retained(root, good, raw, form)
    original = good.skills[0].validation.candidate if child else good.candidate
    assert original is not None
    copied = original.model_copy(update={field: candidate[field]})
    if child:
        binding = good.skills[0]
        validation = binding.validation.model_copy(update={"candidate": copied})
        forged = good.model_copy(update={"skills": (binding.model_copy(update={"validation": validation}),)})
    else:
        forged = good.model_copy(update={"candidate": copied})
    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(forged)


@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
@pytest.mark.parametrize("inline", [False, True])
def test_captured_settings_fallback_cannot_select_none(tmp_path: Path, form: str, inline: bool) -> None:
    """A captured overlay must be selected or superseded, never silently absent."""
    root = _fixture(tmp_path)
    overlay = root / ".codex-plugin" / "plugin.json"
    overlay.parent.mkdir()
    overlay.write_text("invalid unused overlay" if inline else "{}", encoding="utf-8")
    if inline:
        manifest = root / "plugin.json"
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        metadata["extensions"] = {"com.openai": {}}
        manifest.write_text(json.dumps(metadata), encoding="utf-8")
    good = validate_plugin_package(root, source_revision=REVISION)
    assert good.status == "pass" and good.manifest is not None
    assert good.manifest.openai_settings_source == ("inline" if inline else "compatibility")
    raw = good.model_dump(mode="json")
    raw["manifest"].update(openai_settings_source="none", openai_settings_sha256=None)
    _reject_retained(root, good, raw, form)


@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
@pytest.mark.parametrize("change", ["remove", "wrong_severity"])
def test_mcp_warning_cannot_be_removed_or_reclassified(tmp_path: Path, form: str, change: str) -> None:
    """Retained MCP bytes require the explicit unassessed warning even when blocked."""
    root = _fixture(tmp_path)
    (root / "mcp.json").write_bytes(b"unparsed MCP bytes")
    good = validate_plugin_package(root, source_revision=REVISION)
    assert good.status == "pass"
    raw = good.model_dump(mode="json")
    warning = next(item for item in raw["findings"] if item["code"] == "plugin_mcp_not_assessed")
    if change == "remove":
        raw["findings"].remove(warning)
    else:
        warning["severity"] = "blocker"
        raw["status"] = "blocked"
    _reject_retained(root, good, raw, form)


@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
@pytest.mark.parametrize("field", ["version", "description"])
@pytest.mark.parametrize("value", [None, "", " \t\n"])
@pytest.mark.parametrize("change", ["remove", "downgrade"])
def test_required_metadata_blocker_cannot_be_hidden(
    tmp_path: Path, form: str, field: str, value: str | None, change: str
) -> None:
    """Retain specific policy failures even when an unrelated issue already blocks."""
    root = _fixture(tmp_path)
    manifest = root / "plugin.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if value is not None:
        metadata[field] = value
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    policy = PluginValidationPolicy.model_validate({"require_" + field: True})
    blocked = validate_plugin_package(root, source_revision=REVISION, policy=policy)
    code = "sdk_plugin_" + field + "_required"
    assert blocked.status == "blocked" and blocked.candidate is not None
    raw = blocked.model_dump(mode="json")
    finding = next(item for item in raw["findings"] if item["code"] == code)
    raw["findings"].append({**finding, "code": "unrelated_blocker"})
    if change == "remove":
        raw["findings"].remove(finding)
    else:
        finding["severity"] = "warning"
    _reject_retained(root, blocked, raw, form)
    metadata[field] = "1.0.0" if field == "version" else "Synthetic description."
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    recovered = validate_plugin_package(root, source_revision=REVISION, policy=policy)
    assert recovered.status == "pass"
    assert verify_plugin_package_validation(root, recovered, source_revision=REVISION, policy=policy) == recovered


def test_blocked_child_requires_its_specific_parent_finding(tmp_path: Path) -> None:
    """An unrelated parent blocker cannot replace the deterministic child failure."""
    root = _fixture(tmp_path)
    (root / "skills" / "fixture-skill" / "SKILL.md").write_text("---\nname: [\n", encoding="utf-8")
    blocked = validate_plugin_package(root, source_revision=REVISION)
    raw = blocked.model_dump(mode="json")
    finding = next(item for item in raw["findings"] if item["code"] == "plugin_child_blocked")
    finding["code"] = "unrelated_blocker"
    _reject_retained(root, blocked, raw, "raw")


@pytest.mark.parametrize("field", ["sha256", "package_id", "name"])
def test_child_canonical_string_siblings_reject_copied_padding(tmp_path: Path, field: str) -> None:
    """Keep nested hashes and parsed child names exact before shared model normalisation."""
    root = _fixture(tmp_path)
    good = validate_plugin_package(root, source_revision=REVISION)
    binding = good.skills[0]
    raw = good.model_dump(mode="json")
    child = raw["skills"][0]["validation"]
    if field == "sha256":
        child["files"][0][field] = " " + child["files"][0][field] + "\t"
        files = list(binding.validation.files)
        files[0] = files[0].model_copy(update={field: child["files"][0][field]})
        validation = binding.validation.model_copy(update={"files": tuple(files)})
    else:
        child["identity"][field] = " " + child["identity"][field] + "\t"
        assert binding.validation.identity is not None
        identity = binding.validation.identity.model_copy(update={field: child["identity"][field]})
        validation = binding.validation.model_copy(update={"identity": identity})
    _reject_retained(root, good, raw, "raw")
    forged = good.model_copy(update={"skills": (binding.model_copy(update={"validation": validation}),)})
    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(forged)


def test_absent_settings_and_descriptive_whitespace_remain_valid(tmp_path: Path) -> None:
    """Preserve optional fields, descriptive whitespace and empty unbound failures."""
    root = _fixture(tmp_path)
    manifest = root / "plugin.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    metadata.update(description="  Synthetic description.  ", version=" \t ")
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    good = validate_plugin_package(root, source_revision=REVISION)
    assert good.status == "pass" and good.manifest is not None
    assert good.manifest.description == metadata["description"]
    assert good.manifest.version == metadata["version"]
    assert good.manifest.openai_settings_source == "none"
    assert verify_plugin_package_validation(root, good, source_revision=REVISION) == good
    overlay = root / ".codex-plugin" / "plugin.json"
    overlay.parent.mkdir()
    overlay.write_text("malformed selected overlay", encoding="utf-8")
    blocked = validate_plugin_package(
        root, source_revision=REVISION, policy=PluginValidationPolicy(require_version=True)
    )
    assert blocked.status == "blocked" and blocked.candidate is None and not blocked.files
    assert PluginPackageValidation.model_validate(blocked) == blocked
    SchemaRegistry().validate("plugin-package-validation.v1", blocked.model_dump(mode="json"))


def test_pre_normalised_shared_identity_remains_canonical(tmp_path: Path) -> None:
    """Do not reinterpret frozen standalone parsing or invent discarded provenance."""
    from skills_sdk.models.package import PackageCandidateIdentity

    root = _fixture(tmp_path)
    good = validate_plugin_package(root, source_revision=REVISION)
    assert good.candidate is not None
    raw = good.candidate.model_dump(mode="json")
    raw["package_id"] = " " + raw["package_id"] + " "
    canonical = PackageCandidateIdentity.model_validate(raw)
    assert canonical == good.candidate
    assert PluginPackageValidation.model_validate(good.model_copy(update={"candidate": canonical})) == good


@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
@pytest.mark.parametrize("blocked", [False, True])
def test_padded_finding_codes_cannot_be_normalised(tmp_path: Path, form: str, blocked: bool) -> None:
    """Require exact warning and blocker codes before shared finding models strip them."""
    root = _fixture(tmp_path)
    (root / "mcp.json").write_bytes(b"unparsed MCP")
    good = validate_plugin_package(
        root, source_revision=REVISION, policy=PluginValidationPolicy(require_version=blocked)
    )
    raw = good.model_dump(mode="json")
    code = "sdk_plugin_version_required" if blocked else "plugin_mcp_not_assessed"
    finding = next(item for item in raw["findings"] if item["code"] == code)
    finding["code"] = " " + code + "\t"
    _reject_retained(root, good, raw, form)
    copied = tuple(
        item.model_copy(update={"code": " " + code + "\t"}) if item.code == code else item for item in good.findings
    )
    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(good.model_copy(update={"findings": copied}))
