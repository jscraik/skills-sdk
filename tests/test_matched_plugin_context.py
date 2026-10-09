"""Whole-plugin generator context binding and source-stability regressions."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation import matched_plugin_context as service
from skills_sdk.evaluation.matched_plugin_context import PluginExecutionContext, prepare_matched_plugin_context
from skills_sdk.evaluation.selected_case import load_selected_case
from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI
from skills_sdk.validation.plugin_package import validate_plugin_package

REVISION = "1" * 40


def _case() -> dict[str, object]:
    """Return one minimal selected-case definition."""
    return {
        "id": "happy",
        "category": "happy",
        "prompt": "Review the plugin.",
        "eval_modes": ["release"],
        "deterministic_checks": {"forbidden_commands": []},
        "acceptance": [{"type": "expected_signal", "value": "Bound evidence."}],
    }


def _plugin(tmp_path: Path, names: tuple[str, ...] = ("alpha",)) -> Path:
    """Create a valid multi-skill plugin fixture with private evaluation documents."""
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "plugin.json").write_text(json.dumps({"$schema": PLUGIN_SCHEMA_URI, "name": "context-plugin"}))
    references = root / "references"
    references.mkdir()
    (references / "shared.md").write_text("Shared public guidance.\n")
    (references / "hidden-evals.md").write_text("secret label\n")
    for name in names:
        child = root / "skills" / name
        (child / "references").mkdir(parents=True)
        (child / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Test {name}.\n---\n# {name}\n", encoding="utf-8"
        )
        (child / "references" / "evals.yaml").write_text(
            yaml.safe_dump({"schema_version": "2.0", "skill_name": name, "cases": [_case()]}), encoding="utf-8"
        )
    return root


def _prepared(root: Path, selected: tuple[str, ...]) -> tuple[object, PluginExecutionContext]:
    """Load the driver case and construct retained whole-plugin context."""
    validation = validate_plugin_package(root, source_revision=REVISION)
    assert validation.status == "pass"
    driver = selected[0]
    definition = load_selected_case(root / driver, source_revision=REVISION, case_id="happy", mode="release")
    context = PluginExecutionContext(
        root=root,
        validation=validation,
        driver_skill_path=driver,
        selected_skill_paths=selected,
        reference_paths=("references/shared.md",),
    )
    return definition, context


def test_single_and_multiple_child_contexts_bind_complete_plugin(tmp_path: Path) -> None:
    """Include whole-plugin identity, mode, selected child identities and captured text."""
    root = _plugin(tmp_path, ("alpha", "beta"))
    definition, context = _prepared(root, ("skills/alpha", "skills/beta"))
    payload = prepare_matched_plugin_context(definition, context)
    plugin = payload["plugin_context"]
    assert plugin["candidate"] == context.validation.candidate.model_dump(mode="json")
    assert plugin["mode_manifest_sha256"] == context.validation.mode_manifest_sha256
    assert [item["path"] for item in plugin["selected_skills"]] == ["skills/alpha", "skills/beta"]
    assert [item["path"] for item in plugin["documents"]] == [
        "skills/alpha/SKILL.md",
        "skills/beta/SKILL.md",
        "references/shared.md",
    ]
    assert str(root) not in json.dumps(payload)


@pytest.mark.parametrize("reference", ["skills/beta/SKILL.md", "skills/beta/references/guide.md"])
def test_unselected_child_references_block_and_selected_shared_recover(tmp_path: Path, reference: str) -> None:
    """Runtime context must not silently widen declared per-skill selection."""
    root = _plugin(tmp_path, ("alpha", "beta"))
    for name in ("alpha", "beta"):
        (root / "skills" / name / "references" / "guide.md").write_text(f"Private {name} instructions.\n")
    definition, context = _prepared(root, ("skills/alpha",))
    with pytest.raises(ContractError, match="selected child"):
        prepare_matched_plugin_context(definition, replace(context, reference_paths=(reference,)))
    safe = replace(context, reference_paths=("references/shared.md", "skills/alpha/references/guide.md"))
    documents = prepare_matched_plugin_context(definition, safe)["plugin_context"]["documents"]
    assert [item["path"] for item in documents] == [
        "skills/alpha/SKILL.md",
        "references/shared.md",
        "skills/alpha/references/guide.md",
    ]
    assert "Private beta instructions." not in json.dumps(documents)
    cross = replace(context, selected_skill_paths=("skills/alpha", "skills/beta"))
    if reference.endswith("SKILL.md"):
        reference = "skills/beta/references/guide.md"
    assert prepare_matched_plugin_context(definition, replace(cross, reference_paths=(reference,)))


def test_relative_plugin_root_retains_same_context_without_following_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host-root spelling is not part of portable candidate identity."""
    root = _plugin(tmp_path)
    definition, context = _prepared(root, ("skills/alpha",))
    expected = prepare_matched_plugin_context(definition, context)
    monkeypatch.chdir(tmp_path)
    relative = replace(context, root=Path("plugin"))
    assert prepare_matched_plugin_context(definition, relative) == expected
    link = tmp_path / "linked"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ContractError):
        prepare_matched_plugin_context(definition, replace(context, root=Path("linked")))
    assert prepare_matched_plugin_context(definition, relative) == expected


@pytest.mark.parametrize("mutation", ["shared", "mode", "child"])
def test_source_drift_is_rejected_and_corrected_input_recovers(tmp_path: Path, mutation: str) -> None:
    """Reject shared-file, mode and child-byte drift, then accept freshly retained evidence."""
    root = _plugin(tmp_path)
    definition, context = _prepared(root, ("skills/alpha",))
    target = root / ("references/shared.md" if mutation == "shared" else "skills/alpha/SKILL.md")
    if mutation == "mode":
        os.chmod(target, 0o744)
    else:
        target.write_text(target.read_text() + "changed\n", encoding="utf-8")
    with pytest.raises(ContractError):
        prepare_matched_plugin_context(definition, context)
    if mutation == "mode":
        os.chmod(target, 0o644)
    else:
        target.write_text(target.read_text().removesuffix("changed\n"), encoding="utf-8")
    assert prepare_matched_plugin_context(definition, context)["prompt"] == "Review the plugin."


@pytest.mark.parametrize("reference", ["../shared.md", "references/hidden-evals.md", "references/missing.md"])
def test_unsafe_hidden_and_unknown_references_are_rejected(tmp_path: Path, reference: str) -> None:
    """Reject traversal, hidden evaluation material and uncaptured reference paths."""
    root = _plugin(tmp_path)
    definition, context = _prepared(root, ("skills/alpha",))
    context = replace(context, reference_paths=(reference,))
    with pytest.raises(ContractError):
        prepare_matched_plugin_context(definition, context)


@pytest.mark.parametrize(
    "field,value",
    [
        ("selected_skill_paths", ([],)),
        ("selected_skill_paths", (None,)),
        ("reference_paths", ([],)),
        ("reference_paths", (1,)),
        ("driver_skill_path", []),
    ],
)
def test_noncanonical_selection_returns_typed_blocker_and_recovers(tmp_path: Path, field: str, value: object) -> None:
    root = _plugin(tmp_path)
    definition, context = _prepared(root, ("skills/alpha",))
    with pytest.raises(ContractError, match="invalid_matched_plugin_context"):
        prepare_matched_plugin_context(definition, replace(context, **{field: value}))
    assert prepare_matched_plugin_context(definition, context)["prompt"] == "Review the plugin."


def test_symlink_reference_is_rejected_without_mutation(tmp_path: Path) -> None:
    """Reject a selected symlink while preserving its target and plugin source."""
    root = _plugin(tmp_path)
    definition, context = _prepared(root, ("skills/alpha",))
    target = tmp_path / "outside.md"
    target.write_text("outside\n", encoding="utf-8")
    link = root / "references" / "linked.md"
    link.symlink_to(target)
    context = replace(context, reference_paths=("references/linked.md",))
    with pytest.raises(ContractError):
        prepare_matched_plugin_context(definition, context)
    assert target.read_text(encoding="utf-8") == "outside\n" and link.is_symlink()


def test_source_change_after_document_read_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Require the confirming whole-plugin verification after selected bytes are read."""
    root = _plugin(tmp_path)
    definition, context = _prepared(root, ("skills/alpha",))
    original = service._documents

    def changed_after_read(value: PluginExecutionContext) -> list[object]:
        """Mutate a shared file only after the helper has captured its document bytes."""
        documents = original(value)
        (root / "references" / "shared.md").write_text("changed after read\n", encoding="utf-8")
        return documents

    monkeypatch.setattr(service, "_documents", changed_after_read)
    with pytest.raises(ContractError, match="unchanged verified source"):
        prepare_matched_plugin_context(definition, context)


def test_driver_root_and_child_identity_must_match(tmp_path: Path) -> None:
    """Reject a definition whose child identity or package root is not the driver binding."""
    root = _plugin(tmp_path, ("alpha", "beta"))
    definition, context = _prepared(root, ("skills/alpha", "skills/beta"))
    wrong_root = replace(definition, _package_root=root / "skills" / "beta")
    with pytest.raises(ContractError, match=r"definition failed revalidation|package root"):
        prepare_matched_plugin_context(wrong_root, context)
    beta = load_selected_case(root / "skills" / "beta", source_revision=REVISION, case_id="happy", mode="release")
    with pytest.raises(ContractError, match="driver definition"):
        prepare_matched_plugin_context(beta, context)


def test_selection_is_sorted_unique_and_includes_driver(tmp_path: Path) -> None:
    """Reject ambiguous child selection while leaving valid evidence reusable."""
    root = _plugin(tmp_path, ("alpha", "beta"))
    definition, context = _prepared(root, ("skills/alpha", "skills/beta"))
    for selected in (("skills/beta", "skills/alpha"), ("skills/alpha", "skills/alpha"), ("skills/beta",)):
        with pytest.raises(ContractError):
            prepare_matched_plugin_context(definition, replace(context, selected_skill_paths=selected))
    assert prepare_matched_plugin_context(definition, context)["plugin_context"]["driver_skill_path"] == "skills/alpha"
