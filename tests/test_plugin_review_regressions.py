"""Public-boundary regressions from the portable-plugin review."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.packaging import PackageFileRole
from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI, PluginPackageValidation
from skills_sdk.validation.plugin_package import validate_plugin_package
from skills_sdk.validation.skill_package import validate_skill_package

REVISION = "1" * 40
ROLE_PATHS = (
    "SKILL.md",
    "README.md",
    "references/example.md",
    "scripts/example.py",
    "assets/example.txt",
    "evals/example.json",
)


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path.resolve() / "plugin"
    child = root / "skills" / "fixture-skill"
    child.mkdir(parents=True)
    for name in ROLE_PATHS:
        target = child / name
        target.parent.mkdir(parents=True, exist_ok=True)
        text = "Synthetic fixture.\n"
        if name == "SKILL.md":
            text = "---\nname: fixture-skill\ndescription: Inspect synthetic examples.\n---\n# Example\n"
        elif name.endswith(".json"):
            text = "{}\n"
        target.write_text(text, encoding="utf-8")
    metadata: dict[str, object] = {"$schema": PLUGIN_SCHEMA_URI, "name": "fixture-plugin"}
    _manifest(root, metadata)
    return root, metadata


def _manifest(root: Path, metadata: dict[str, object]) -> None:
    (root / "plugin.json").write_text(json.dumps(metadata), encoding="utf-8")


def _valid(root: Path) -> PluginPackageValidation:
    result = validate_plugin_package(root, source_revision=REVISION)
    assert result.status == "pass", result.model_dump(mode="json")
    return result


def _forged_role(good: PluginPackageValidation, path: str, form: str) -> object:
    child = good.skills[0]
    records = tuple(
        item.model_copy(
            update={"role": PackageFileRole.ASSET if path != "assets/example.txt" else PackageFileRole.SCRIPT}
        )
        if item.path == path
        else item
        for item in child.validation.files
    )
    changed = child.model_copy(update={"validation": child.validation.model_copy(update={"files": records})})
    if form == "raw":
        raw = good.model_dump(mode="json")
        raw["skills"] = [changed.model_dump(mode="json")]
        return raw
    if form == "copy":
        return good.model_copy(update={"skills": (changed,)})
    return PluginPackageValidation.model_construct(**{**good.__dict__, "skills": (changed,)})


@pytest.mark.parametrize("path", ROLE_PATHS)
@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
@pytest.mark.parametrize("boundary", ["model", "registry"])
def test_child_file_roles_are_bound(tmp_path: Path, path: str, form: str, boundary: str) -> None:
    root, _ = _fixture(tmp_path)
    good = _valid(root)
    forged = _forged_role(good, path, form)
    if boundary == "model":
        with pytest.raises(ValueError):
            PluginPackageValidation.model_validate(forged)
        assert PluginPackageValidation.model_validate(good) == good
    else:
        payload = forged if isinstance(forged, dict) else forged.model_dump(mode="json")
        with pytest.raises(ContractError):
            SchemaRegistry().validate("plugin-package-validation.v1", payload)
        SchemaRegistry().validate("plugin-package-validation.v1", good.model_dump(mode="json"))


def test_all_canonical_child_roles_preserve_standalone_compatibility(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    good = _valid(root)
    standalone = validate_skill_package(root / "skills" / "fixture-skill", source_revision=REVISION)
    assert good.skills[0].validation == standalone
    assert {item.role for item in standalone.files} == set(PackageFileRole)
    SchemaRegistry().validate("skill-package-validation.v1", standalone.model_dump(mode="json"))
    SchemaRegistry().validate("plugin-package-validation.v1", good.model_dump(mode="json"))


def _warning_messages(result: PluginPackageValidation) -> tuple[str, ...]:
    warnings = tuple(item for item in result.findings if item.code == "plugin_unknown_fields_ignored")
    assert warnings and all(item.severity == "warning" and item.evidence_refs == ("plugin.json",) for item in warnings)
    return tuple(item.message for item in warnings)


def test_unknown_keys_are_json_escaped_named_sorted_without_values(tmp_path: Path) -> None:
    root, metadata = _fixture(tmp_path)
    names = ("z-last", "descrption", 'quoted"key', "line\nkey", "a-first")
    metadata.update(dict.fromkeys(names, "DO-NOT-RETAIN-UNKNOWN-VALUE"))
    _manifest(root, metadata)
    good = _valid(root)
    messages = "\n".join(_warning_messages(good))
    escaped = [json.dumps(name) for name in sorted(names)]
    assert all(name in messages for name in escaped)
    assert [messages.index(name) for name in escaped] == sorted(messages.index(name) for name in escaped)
    assert "DO-NOT-RETAIN-UNKNOWN-VALUE" not in messages
    assert _warning_messages(_valid(root)) == _warning_messages(good)
    _manifest(root, {"$schema": PLUGIN_SCHEMA_URI, "name": "fixture-plugin"})
    assert not _valid(root).findings


def test_many_unknown_keys_pass_with_bounded_deterministic_diagnostic(tmp_path: Path) -> None:
    root, metadata = _fixture(tmp_path)
    metadata.update({f"unknown-{index:04d}": "PRIVATE-UNKNOWN-VALUE" for index in range(2050)})
    _manifest(root, metadata)
    good = _valid(root)
    messages = _warning_messages(good)
    assert len(messages) == 1 and sum(map(len, messages)) <= 131072
    assert all(json.dumps(f"unknown-{index:04d}") in messages[0] for index in range(2050))
    assert "PRIVATE-UNKNOWN-VALUE" not in "\n".join(messages)
    assert _warning_messages(_valid(root)) == messages
    SchemaRegistry().validate("plugin-package-validation.v1", good.model_dump(mode="json"))


@pytest.mark.parametrize("name", ["SKILL-md", "SKILLXmd"])
@pytest.mark.parametrize("actual", [False, True])
def test_discovery_requires_literal_entrypoint(tmp_path: Path, name: str, actual: bool) -> None:
    root, _ = _fixture(tmp_path)
    entry = root / "skills" / "fixture-skill" / "SKILL.md"
    (entry.parent / name).write_bytes(entry.read_bytes())
    if not actual:
        entry.unlink()
    good = _valid(root)
    assert tuple(item.path for item in good.skills) == (("skills/fixture-skill",) if actual else ())
    SchemaRegistry().validate("plugin-package-validation.v1", good.model_dump(mode="json"))
    if not actual:
        entry.write_bytes((entry.parent / name).read_bytes())
        assert len(_valid(root).skills) == 1


@pytest.mark.parametrize("name", ["SKILL-md", "SKILLXmd", "SKILL.md"])
def test_entrypoint_directory_kind_is_literal(tmp_path: Path, name: str) -> None:
    root, _ = _fixture(tmp_path)
    entry = root / "skills" / "fixture-skill" / "SKILL.md"
    original = entry.read_bytes()
    entry.unlink()
    directory = entry.parent / name
    directory.mkdir()
    result = validate_plugin_package(root, source_revision=REVISION)
    if name == "SKILL.md":
        assert result.status == "blocked"
        assert "plugin_component_kind_invalid" in {item.code for item in result.findings}
        directory.rmdir()
    else:
        assert result.status == "pass" and result.skills == ()
    entry.write_bytes(original)
    assert len(_valid(root).skills) == 1
