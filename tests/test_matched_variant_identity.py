"""Distinct complete identities are required before matched improvement assessment."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_matched_comparison import _judgment, _plan
from test_matched_plugin_scope import _fixture

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import assess_matched_pair
from skills_sdk.models import MatchedComparisonPlan, MatchedPluginScope
from skills_sdk.validation import validate_plugin_package


def _identical_scope(raw: dict[str, object]) -> dict[str, object]:
    """Bind every candidate-side field to the baseline, not an inconsistent forgery."""
    changed = deepcopy(raw)
    changed["candidate"] = deepcopy(changed["baseline"])
    changed["candidate_coverage"] = deepcopy(changed["baseline_coverage"])
    for case in changed["cases"]:
        case["candidate_scorer"] = deepcopy(case["baseline_scorer"])
    return changed


@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
def test_identical_complete_scope_rejects_and_distinct_original_recovers(form: str) -> None:
    good = _plan().plugin_scope
    raw = _identical_scope(good.model_dump(mode="json"))
    candidate: object = raw
    if form == "copy":
        candidate = good.model_copy(update=raw)
    elif form == "construct":
        candidate = MatchedPluginScope.model_construct(**raw)
    with pytest.raises(ValidationError, match="distinct complete candidate identities"):
        if form == "json":
            MatchedPluginScope.model_validate_json(json.dumps(raw))
        else:
            MatchedPluginScope.model_validate(candidate)
    assert MatchedPluginScope.model_validate(good) == good


@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct", "nested_copy"])
def test_identical_plan_cannot_report_improvement_and_corrected_plan_recovers(form: str) -> None:
    good = _plan()
    raw = good.model_dump(mode="json")
    raw["plugin_scope"] = _identical_scope(raw["plugin_scope"])
    raw["candidate_scenarios"] = deepcopy(raw["baseline_scenarios"])
    candidate: object = raw
    if form == "copy":
        candidate = good.model_copy(update=raw)
    elif form == "construct":
        candidate = MatchedComparisonPlan.model_construct(**raw)
    elif form == "nested_copy":
        candidate = good.model_copy(
            update={
                "plugin_scope": good.plugin_scope.model_copy(update=raw["plugin_scope"]),
                "candidate_scenarios": good.baseline_scenarios,
            }
        )
    rejected = assess_matched_pair(
        candidate, "local", _judgment(good, "baseline", 2.5), _judgment(good, "baseline", 4.0)
    )
    assert rejected.status == "blocked" and rejected.plan is None
    assert rejected.blocker.code == "invalid_matched_judgments"
    with pytest.raises(ValidationError, match="distinct complete candidate identities"):
        if form == "json":
            MatchedComparisonPlan.model_validate_json(json.dumps(raw))
        else:
            MatchedComparisonPlan.model_validate(candidate)
    recovered = assess_matched_pair(good, "local", _judgment(good, "baseline", 2.5), _judgment(good, "candidate", 4.0))
    assert recovered.status == "assessed" and recovered.decision == "candidate"


def test_packaged_schema_semantics_reject_identical_identities_and_recover() -> None:
    good = _plan().model_dump(mode="json")
    raw = deepcopy(good)
    raw["plugin_scope"] = _identical_scope(raw["plugin_scope"])
    raw["candidate_scenarios"] = deepcopy(raw["baseline_scenarios"])
    registry = SchemaRegistry()
    # Structural JSON Schema cannot express inequality between these nested identities.
    Draft202012Validator(registry.load("matched-comparison-plan.v1")).validate(raw)
    with pytest.raises(ContractError, match=r"^contract_validation_failed:"):
        registry.validate("matched-comparison-plan.v1", raw)
    registry.validate("matched-comparison-plan.v1", good)


@pytest.mark.parametrize("difference", ["revision", "content", "revision_and_content"])
def test_same_package_distinct_revision_or_content_remains_accepted(tmp_path: Path, difference: str) -> None:
    raw = _fixture(tmp_path)
    if difference != "revision":
        (tmp_path / "candidate" / "README.md").write_text("Candidate documentation.\n", encoding="utf-8")
        revision = raw["baseline"]["candidate"]["source_revision"] if difference == "content" else "2" * 40
        capture = validate_plugin_package(tmp_path / "candidate", source_revision=revision)
        assert capture.status == "pass"
        raw["candidate"] = capture.model_dump(mode="json")
        raw["candidate_coverage"]["candidate"] = raw["candidate"]["candidate"]
        children = {child["path"]: child["validation"]["candidate"] for child in raw["candidate"]["skills"]}
        for case in raw["cases"]:
            case["candidate_scorer"]["candidate"] = children[case["driver_skill_path"]]
    good = MatchedPluginScope.model_validate(raw)
    left, right = good.baseline.candidate, good.candidate.candidate
    assert left.package_id == right.package_id and left != right
    assert (left.source_revision != right.source_revision) is (difference != "content")
    assert (left.content_sha256 != right.content_sha256) is (difference != "revision")
    assert MatchedPluginScope.model_validate_json(good.model_dump_json()) == good
