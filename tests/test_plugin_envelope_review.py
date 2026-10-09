"""Retained plugin evidence must preserve canonical types and component kinds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI, PluginPackageValidation
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
