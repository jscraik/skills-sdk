"""Whole-plugin ten-case coverage joins without provider or runtime operations."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from skills_sdk.models.matched_plugin_scope import MatchedPluginCaseScope, MatchedPluginScope
from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI
from skills_sdk.validation import validate_plugin_package


def _capture(root: Path, count: int, revision: str) -> dict[str, object]:
    """Use the accepted capture producer rather than constructing a fake file ledger."""
    root.mkdir()
    (root / "README.md").write_text("# Public matched fixture guidance\n", encoding="utf-8")
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": PLUGIN_SCHEMA_URI,
                "name": "fixture-plugin",
                "version": "1.0.0",
                "description": "Synthetic matched fixture.",
            }
        ),
        encoding="utf-8",
    )
    for index in range(count):
        child = root / "skills" / f"skill-{index}"
        child.mkdir(parents=True)
        (child / "SKILL.md").write_text(
            f"---\nname: skill-{index}\ndescription: Synthetic fixture.\n---\n# Fixture\n", encoding="utf-8"
        )
    capture = validate_plugin_package(root, source_revision=revision)
    assert capture.status == "pass"
    return capture.model_dump(mode="json")


def _scorer(candidate: object) -> dict[str, object]:
    """Retain child-bound declaration; this does not claim executed calibration."""
    return {
        "candidate": candidate,
        "scorer_id": "fixture-scorer",
        "scorer_type": "llm_judge",
        "version_or_digest": "v1",
        "pass_threshold": 0.5,
        "deterministic_checks_first": True,
        "calibration_required": True,
        "calibration_probe_ids": ["held-out-0"],
    }


def _fixture(tmp_path: Path, count: int = 2) -> dict[str, object]:
    """Freeze two captures and ten cases with explicit joins to existing coverage claims."""
    baseline = _capture(tmp_path / "baseline", count, "1" * 40)
    candidate = _capture(tmp_path / "candidate", count, "2" * 40)
    children = max(count, 1)
    cases = []
    for index in range(10):
        driver = index % children
        path = f"skills/skill-{driver}"
        cross = count > 1 and index == 9
        cases.append(
            {
                "case_id": f"case-{index}",
                "scope": "cross_skill" if cross else "per_skill",
                "driver_skill_path": path,
                "selected_skill_paths": [f"skills/skill-{n}" for n in range(count)] if cross else [path],
                "baseline_scorer": _scorer(
                    baseline["skills"][driver]["validation"]["candidate"] if count else baseline["candidate"]
                ),
                "candidate_scorer": _scorer(
                    candidate["skills"][driver]["validation"]["candidate"] if count else candidate["candidate"]
                ),
                "claim_ids": [f"claim-{index}"],
            }
        )
    coverage = {
        "scenario_set_id": "managed-ten",
        "claims": [{"id": f"claim-{index}", "statement": "Synthetic declared behaviour."} for index in range(10)],
        "mappings": [{"claim_id": f"claim-{index}", "case_ids": [f"case-{index}"]} for index in range(10)],
    }
    return {
        "baseline": baseline,
        "candidate": candidate,
        "cases": cases,
        "baseline_coverage": {**coverage, "candidate": baseline["candidate"]},
        "candidate_coverage": {**deepcopy(coverage), "candidate": candidate["candidate"]},
    }


@pytest.mark.parametrize("count", [1, 2, 9])
def test_complete_plugin_scope_accepts_bound_one_two_nine_children(tmp_path: Path, count: int) -> None:
    raw = _fixture(tmp_path, count)
    good = MatchedPluginScope.model_validate(raw)
    assert len(good.cases) == 10 and len(good.baseline.skills) == count
    assert MatchedPluginScope.model_validate(good) == good
    Draft202012Validator(MatchedPluginScope.model_json_schema()).validate(raw)
    assert good.baseline.candidate != good.candidate.candidate


@pytest.mark.parametrize("count", [0, 10])
def test_capacity_limitation_is_named_not_complete_coverage(tmp_path: Path, count: int) -> None:
    raw = _fixture(tmp_path, count)
    if count == 10:
        raw["cases"][-1]["selected_skill_paths"] = ["skills/skill-0", "skills/skill-9"]
    with pytest.raises(ValueError, match="matched_plugin_capacity") as rejected:
        MatchedPluginScope.model_validate(raw)
    assert rejected.value.errors()[0]["type"] == "matched_plugin_capacity"


@pytest.mark.parametrize(
    "kind",
    [
        "omission",
        "unknown",
        "duplicate",
        "cross",
        "wrong_child",
        "contract",
        "mode",
        "claim",
        "unmapped",
        "objective",
        "coverage_candidate",
        "gap",
        "padding",
    ],
)
@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
def test_forged_scope_rejects_and_original_recovers(tmp_path: Path, kind: str, form: str) -> None:
    raw = _fixture(tmp_path)
    good = MatchedPluginScope.model_validate(raw)
    bad = deepcopy(raw)
    if kind == "omission":
        for case in bad["cases"]:
            if case["scope"] == "per_skill" and case["driver_skill_path"] == "skills/skill-1":
                case.update(
                    driver_skill_path="skills/skill-0",
                    selected_skill_paths=["skills/skill-0"],
                    baseline_scorer=_scorer(raw["baseline"]["skills"][0]["validation"]["candidate"]),
                    candidate_scorer=_scorer(raw["candidate"]["skills"][0]["validation"]["candidate"]),
                )
    elif kind == "unknown":
        bad["cases"][-1]["selected_skill_paths"] = ["skills/skill-0", "skills/unknown"]
    elif kind == "duplicate":
        bad["cases"][1]["case_id"] = bad["cases"][0]["case_id"]
    elif kind == "cross":
        case = bad["cases"][-1]
        case.update(scope="per_skill", selected_skill_paths=[case["driver_skill_path"]])
    elif kind == "wrong_child":
        bad["cases"][0]["baseline_scorer"]["candidate"] = raw["baseline"]["candidate"]
    elif kind == "contract":
        bad["cases"][0]["candidate_scorer"]["scorer_id"] = "other"
    elif kind == "mode":
        bad["baseline"]["files"][0]["permission_mode"] = True
    elif kind == "claim":
        bad["cases"][0]["claim_ids"] = ["claim-1"]
    elif kind == "unmapped":
        bad["baseline_coverage"]["mappings"] = []
    elif kind == "objective":
        bad["candidate_coverage"]["claims"][0]["statement"] = "Changed declared objective."
    elif kind == "coverage_candidate":
        bad["baseline_coverage"]["candidate"] = raw["candidate"]["candidate"]
    elif kind == "gap":
        for name in ("baseline_coverage", "candidate_coverage"):
            bad[name]["gaps"] = [{"id": "open-gap", "reason": "Absent evidence.", "owner": "maintainer"}]
            bad[name]["mappings"][0].update(case_ids=[], gap_ids=["open-gap"])
    else:
        bad["cases"][0]["claim_ids"] = [" claim-0 "]
    forged = (
        bad
        if form == "raw"
        else (good.model_copy(update=bad) if form == "copy" else MatchedPluginScope.model_construct(**bad))
    )
    with pytest.raises(ValueError):
        MatchedPluginScope.model_validate(forged)
    assert MatchedPluginScope.model_validate(good) == good


def test_case_order_is_retained_for_plan_join_not_silently_sorted(tmp_path: Path) -> None:
    raw = _fixture(tmp_path)
    raw["cases"] = list(reversed(raw["cases"]))
    scope = MatchedPluginScope.model_validate(raw)
    assert scope.cases[0].case_id == "case-9"
    raw["cases"].pop()
    with pytest.raises(ValueError):
        MatchedPluginScope.model_validate(raw)


def test_schema_rejects_malformed_mode_and_missing_cases(tmp_path: Path) -> None:
    raw = _fixture(tmp_path)
    validator = Draft202012Validator(MatchedPluginScope.model_json_schema())
    raw["baseline"]["files"][0]["permission_mode"] = True
    assert list(validator.iter_errors(raw))


@pytest.mark.parametrize("field", ["driver_skill_path", "selected_skill_paths"])
def test_raw_paths_cannot_be_trimmed_before_binding(tmp_path: Path, field: str) -> None:
    raw = _fixture(tmp_path)
    raw["cases"][0][field] = " skills/skill-0 " if field == "driver_skill_path" else [" skills/skill-0 "]
    with pytest.raises(ValueError):
        MatchedPluginScope.model_validate(raw)


def test_actual_nested_copied_capture_mode_forgery_rejects(tmp_path: Path) -> None:
    good = MatchedPluginScope.model_validate(_fixture(tmp_path))
    files = list(good.baseline.files)
    files[0] = files[0].model_copy(update={"permission_mode": True})
    forged_capture = good.baseline.model_copy(update={"files": tuple(files)})
    forged = good.model_copy(update={"baseline": forged_capture})
    with pytest.raises(ValueError):
        MatchedPluginScope.model_validate(forged)
    assert MatchedPluginScope.model_validate(good) == good


@pytest.mark.parametrize("reference", ["skills/skill-1/SKILL.md", "skills/skill-1/references/guide.md"])
@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
def test_case_references_cannot_select_an_unselected_child(tmp_path: Path, reference: str, form: str) -> None:
    """References cannot widen a per-skill declaration into undeclared sibling instructions."""
    scope = MatchedPluginScope.model_validate(_fixture(tmp_path))
    good = scope.cases[0]
    raw = good.model_dump(mode="json")
    raw["reference_paths"] = [reference]
    forged = raw
    if form == "copy":
        forged = good.model_copy(update={"reference_paths": (reference,)})
    elif form == "construct":
        forged = MatchedPluginCaseScope.model_construct(**raw)
    with pytest.raises(ValueError, match="selected child"):
        if form == "json":
            MatchedPluginCaseScope.model_validate_json(json.dumps(raw))
        else:
            MatchedPluginCaseScope.model_validate(forged)
    # Structural JSON Schema cannot express this cross-field membership join.
    Draft202012Validator(MatchedPluginCaseScope.model_json_schema()).validate(raw)
    safe = good.model_copy(update={"reference_paths": ("references/shared.md", "skills/skill-0/references/guide.MD")})
    assert MatchedPluginCaseScope.model_validate(safe) == safe
    cross = scope.cases[-1].model_copy(update={"reference_paths": (reference,)})
    if reference.endswith("SKILL.md"):
        with pytest.raises(ValueError, match="automatic selected entrypoints"):
            MatchedPluginCaseScope.model_validate(cross)
    else:
        assert MatchedPluginCaseScope.model_validate(cross) == cross


def test_registry_rejects_unselected_child_reference_and_recovers() -> None:
    """Packaged registry semantic validation retains the selected-child boundary."""
    from test_matched_comparison import _plan

    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry

    good = _plan().model_dump(mode="json")
    forged = deepcopy(good)
    case = forged["plugin_scope"]["cases"][0]
    unselected = next(
        child
        for child in forged["plugin_scope"]["baseline"]["skills"]
        if child["path"] not in case["selected_skill_paths"]
    )
    case["reference_paths"] = [f"{unselected['path']}/SKILL.md"]
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-comparison-plan.v1", forged)
    SchemaRegistry().validate("matched-comparison-plan.v1", good)
