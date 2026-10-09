"""Candidate binding regressions for blocked portable-plugin children."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from skills_sdk.core.digests import candidate_content_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI, PluginPackageValidation, PortablePluginManifest
from skills_sdk.validation.plugin_package import validate_plugin_package

REVISION = "1" * 40


def _fixture(tmp_path: Path, child_name: str = "fixture-skill") -> tuple[Path, Path]:
    """Create a plugin containing a child with malformed frontmatter."""
    root = tmp_path.resolve() / "plugin"
    child = root / "skills" / child_name
    child.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"$schema": PLUGIN_SCHEMA_URI, "name": "fixture-plugin"}),
        encoding="utf-8",
    )
    (child / "SKILL.md").write_text("---\nname: [\n", encoding="utf-8")
    return root, child


def _blocked(root: Path) -> PluginPackageValidation:
    """Return the bound plugin result for a blocked child without losing its record."""
    result = validate_plugin_package(root, source_revision=REVISION)
    assert result.status == "blocked"
    assert {item.code for item in result.findings} == {"plugin_child_blocked"}
    assert len(result.skills) == 1
    return result


@pytest.mark.parametrize("child_name", ["fixture-skill", "Invalid_Name"])
def test_blocked_child_candidate_is_canonical_and_roundtrips(tmp_path: Path, child_name: str) -> None:
    """Preserve canonical or fallback child IDs through typed and schema roundtrips."""
    root, _ = _fixture(tmp_path, child_name)
    blocked = _blocked(root)
    child = blocked.skills[0].validation
    assert child.identity is None and child.candidate is not None
    assert child.candidate.source_revision == REVISION
    assert child.candidate.content_sha256 == candidate_content_sha256(child.files)
    if child_name == "fixture-skill":
        expected = child_name
    else:
        root_digest = hashlib.sha256(child_name.encode()).hexdigest()[:6]
        expected = f"invalid-package-{root_digest}-{child.candidate.content_sha256[:12]}"
    assert child.candidate.package_id == expected
    assert isinstance(blocked.manifest, PortablePluginManifest)
    assert PluginPackageValidation.model_validate(blocked) == blocked
    SchemaRegistry().validate("plugin-package-validation.v1", blocked.model_dump(mode="json"))


@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
@pytest.mark.parametrize("child_name", ["fixture-skill", "Invalid_Name"])
def test_blocked_child_candidate_id_forgery_is_rejected(tmp_path: Path, form: str, child_name: str) -> None:
    """Reject replaced child IDs without relying on parsed identity or passing status."""
    root, _ = _fixture(tmp_path, child_name)
    blocked = _blocked(root)
    binding = blocked.skills[0]
    candidate = binding.validation.candidate
    assert candidate is not None
    forged_candidate = candidate.model_copy(update={"package_id": "forged-child"})
    forged_validation = binding.validation.model_copy(update={"candidate": forged_candidate})
    forged_binding = binding.model_copy(update={"validation": forged_validation})
    assert forged_candidate.source_revision == candidate.source_revision
    assert forged_candidate.content_sha256 == candidate.content_sha256

    if form == "raw":
        forged: object = blocked.model_dump(mode="json")
        forged["skills"][0]["validation"]["candidate"]["package_id"] = "forged-child"
    elif form == "copy":
        forged = blocked.model_copy(update={"skills": (forged_binding,)})
    else:
        forged = PluginPackageValidation.model_construct(**{**blocked.__dict__, "skills": (forged_binding,)})

    with pytest.raises(ValueError):
        PluginPackageValidation.model_validate(forged)
    payload = forged if isinstance(forged, dict) else forged.model_dump(mode="json")
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-package-validation.v1", payload)
    assert PluginPackageValidation.model_validate(blocked) == blocked


def test_corrected_child_recovers_with_typed_manifest(tmp_path: Path) -> None:
    """Accept corrected skill metadata while retaining typed manifest compatibility."""
    root, child = _fixture(tmp_path)
    _blocked(root)
    (child / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: Synthetic fixture.\n---\n# Fixture\n",
        encoding="utf-8",
    )
    recovered = validate_plugin_package(root, source_revision=REVISION)
    assert recovered.status == "pass"
    assert isinstance(recovered.manifest, PortablePluginManifest)
    assert recovered.skills[0].validation.identity is not None
    assert recovered.skills[0].validation.candidate is not None
    assert recovered.skills[0].validation.candidate.package_id == "fixture-skill"
    assert not recovered.execution_authorized and not recovered.release_ready and not recovered.mutation_performed
    assert PluginPackageValidation.model_validate(recovered) == recovered
    SchemaRegistry().validate("plugin-package-validation.v1", recovered.model_dump(mode="json"))
