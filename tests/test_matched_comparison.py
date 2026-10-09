"""Matched two-variant contracts, numeric decisions, rejection and recovery."""

from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import ValidationError
from test_matched_plugin_scope import _fixture

from skills_sdk.evaluation.matched_comparison import assess_matched_pair
from skills_sdk.models.matched_comparison import MatchedComparisonPlan, MatchedPairAssessment, MatchedVariantJudgment
from skills_sdk.validation import validate_plugin_package


@lru_cache(maxsize=1)
def _scope_fixture() -> dict[str, object]:
    """Cache only canonical receipts produced from disposable real plugin source."""
    with TemporaryDirectory(prefix="matched-plugin-fixture-") as directory:
        scope = _fixture(Path(directory).resolve(), count=2)
    for case in scope["cases"]:
        for variant in ("baseline", "candidate"):
            case[f"{variant}_scorer"]["calibration_probe_ids"] = [f"probe-{index}" for index in range(6)]
    return scope


def _plan() -> MatchedComparisonPlan:
    """Freeze ten active cases, two distinct candidates and two controlled lanes."""
    scope = deepcopy(_scope_fixture())
    cases = [
        {
            "case_id": f"case-{index}",
            "category": "regression" if index == 9 else "happy",
            "prompt": "Return a bounded review.",
            "expected_signals": ["evidence"],
            "oracle": "expected_signal",
        }
        for index in range(10)
    ]
    lanes = []
    for lane in ("local", "cloud"):
        identity = {
            "provider_id": "fixture",
            "provider_kind": "llm",
            "model_id": f"{lane}-fixture",
            "version_or_digest": "v1",
            "adapter_id": "controlled",
            "adapter_version_or_digest": "v1",
        }
        parameters = {"model": identity["model_id"], "temperature": 0.0, "trial_count": 2}
        lanes.append(
            {
                "lane": lane,
                "generator": identity,
                "generator_parameters": parameters,
                "judge": identity,
                "judge_parameters": parameters,
                "baseline_calibration_sha256": "c" * 64,
                "candidate_calibration_sha256": "d" * 64,
                "budget": {
                    "maximum_provider_invocations": 128,
                    "maximum_judge_invocations": 128,
                    "maximum_elapsed_seconds": 600.0,
                },
            }
        )
    return MatchedComparisonPlan.model_validate(
        {
            "plugin_scope": scope,
            "baseline_scenarios": [
                {
                    "candidate": selected["baseline_scorer"]["candidate"],
                    "scenario_set_id": "managed-ten",
                    "release": False,
                    "cases": [case],
                }
                for selected, case in zip(scope["cases"], cases, strict=True)
            ],
            "candidate_scenarios": [
                {
                    "candidate": selected["candidate_scorer"]["candidate"],
                    "scenario_set_id": "managed-ten",
                    "release": False,
                    "cases": [case],
                }
                for selected, case in zip(scope["cases"], cases, strict=True)
            ],
            "case_bindings": [
                {
                    "case_id": case["case_id"],
                    "baseline_scenario_set_id": "managed-ten",
                    "candidate_scenario_set_id": "managed-ten",
                    "assertion_contract_sha256": "e" * 64,
                    "check_contract_sha256": "e" * 64,
                    "baseline_input_sha256": "f" * 64,
                    "candidate_input_sha256": "a" * 64,
                    "semantic_signal_ids": ["evidence"],
                }
                for case in cases
            ],
            "rubric": {
                "rubric_id": "review-rubric",
                "version_or_digest": "v1",
                "dimensions": [
                    {"dimension_id": "success", "criterion": "Complete the task.", "weight": 0.5},
                    {"dimension_id": "safety", "criterion": "Preserve source.", "weight": 0.5},
                ],
                "minimum_normalized_delta": 0.1,
                "minimum_confidence": "medium",
            },
            "lanes": lanes,
            "selection_policy": {
                "minimum_trials_per_case": 2,
                "minimum_qualifying_case_count": 10,
                "maximum_trial_delta_range": 0.1,
            },
        }
    )


def _judgment(plan: MatchedComparisonPlan, variant: str, score: float) -> MatchedVariantJudgment:
    """Supply dimensional evidence without pretending that a callback ran."""
    return MatchedVariantJudgment.model_validate(
        {
            "evidence": {
                "candidate": getattr(plan.plugin_scope.cases[0], f"{variant}_scorer").candidate.model_dump(mode="json"),
                "scenario_set_id": getattr(plan, f"{variant}_scenarios")[0].scenario_set_id,
                "case_id": "case-0",
                "provider": plan.lanes[0].generator.model_dump(mode="json"),
                "judge": plan.lanes[0].judge.model_dump(mode="json"),
                "output_sha256": "f" * 64,
                "assertion_contract_sha256": "e" * 64,
                "judge_result_sha256": "9" * 64,
                "evidence_refs": ["evidence/judgment.json"],
            },
            "dimensions": [
                {
                    "dimension_id": dimension.dimension_id,
                    "score": score,
                    "rationale": "The retained output supports this score.",
                    "evidence_refs": ["evidence/judgment.json"],
                }
                for dimension in plan.rubric.dimensions
            ],
            "confidence": "medium",
        }
    )


@pytest.mark.parametrize(
    "left,right,decision,regression",
    [
        (2.5, 3.0, "candidate", False),
        (3.0, 2.5, "baseline", True),
        (2.5, 2.5, "inconclusive", False),
        (2.5, 2.4, "inconclusive", True),
    ],
)
def test_recomputed_threshold_ties_and_regressions(left: float, right: float, decision: str, regression: bool) -> None:
    plan = _plan()
    result = assess_matched_pair(plan, "local", _judgment(plan, "baseline", left), _judgment(plan, "candidate", right))
    assert result.status == "assessed" and result.decision == decision
    assert result.regression_required is regression
    assert not result.execution_performed and not result.promotion_authorized
    assert MatchedPairAssessment.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("change", ["case", "dimension", "evidence", "identity", "boolean", "confidence"])
def test_changed_evidence_blocks_and_corrected_input_recovers(change: str) -> None:
    plan = _plan()
    left, right = _judgment(plan, "baseline", 2.5), _judgment(plan, "candidate", 4.0)
    raw = right.model_dump(mode="json")
    if change == "case":
        raw["evidence"]["case_id"] = "case-1"
    elif change == "dimension":
        raw["dimensions"].reverse()
    elif change == "evidence":
        raw["dimensions"][0]["evidence_refs"] = ["evidence/unretained.json"]
    elif change == "identity":
        raw["evidence"]["judge"]["model_id"] = "unbound-model"
    elif change == "boolean":
        raw["dimensions"][0]["score"] = True
    else:
        raw["confidence"] = "low"
    rejected = assess_matched_pair(plan, "local", left, raw)
    if change == "confidence":
        assert rejected.status == "assessed" and rejected.decision == "inconclusive"
    else:
        assert rejected.status == "blocked" and rejected.blocker.code == "invalid_matched_judgments"
    assert assess_matched_pair(plan, "local", left, right).decision == "candidate"


@pytest.mark.parametrize("path", ["../escape", "/absolute/private", "evidence/token=private", "evidence/../escape"])
def test_unsafe_dimension_paths_reject(path: str) -> None:
    plan = _plan()
    right = _judgment(plan, "candidate", 4.0).model_dump(mode="json")
    right["dimensions"][0]["evidence_refs"] = [path]
    assert assess_matched_pair(plan, "local", _judgment(plan, "baseline", 2.5), right).status == "blocked"


def test_unknown_lane_is_typed_blocker_and_recovers() -> None:
    plan = _plan()
    left, right = _judgment(plan, "baseline", 2.5), _judgment(plan, "candidate", 4.0)
    rejected = assess_matched_pair(plan, "unexpected", left, right)
    assert rejected.status == "blocked" and rejected.lane is None
    assert assess_matched_pair(plan, "local", left, right).status == "assessed"


def test_plan_changes_invalidate_identity_and_unmatched_cases_reject() -> None:
    plan = _plan()
    raw = plan.model_dump(mode="json")
    changed = deepcopy(raw)
    changed["lanes"][0]["generator_parameters"]["temperature"] = 0.2
    assert MatchedComparisonPlan.model_validate(changed).digest != plan.digest
    changed = deepcopy(raw)
    changed["candidate_scenarios"][0]["cases"][0]["prompt"] = "Different task."
    with pytest.raises(ValidationError):
        MatchedComparisonPlan.model_validate(changed)


@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
def test_lane_trials_must_meet_selection_minimum_at_every_ingress(form: str) -> None:
    """Reject plans guaranteed to remain inconclusive while retaining a valid neighbour."""
    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry

    plan = _plan()
    raw = plan.model_dump(mode="json")
    raw["lanes"][0]["generator_parameters"]["trial_count"] = 1
    raw["lanes"][0]["judge_parameters"]["trial_count"] = 1
    candidate: object = raw
    if form == "copy":
        candidate = plan.model_copy(update={"lanes": raw["lanes"]})
    elif form == "construct":
        candidate = MatchedComparisonPlan.model_construct(**raw)
    with pytest.raises(ValidationError, match="frozen selection policy"):
        if form == "json":
            MatchedComparisonPlan.model_validate_json(json.dumps(raw))
        else:
            MatchedComparisonPlan.model_validate(candidate)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-comparison-plan.v1", raw)
    assert MatchedComparisonPlan.model_validate(plan) == plan


def test_copied_nested_and_forged_decisions_reject_without_claiming_execution() -> None:
    plan = _plan()
    left, right = _judgment(plan, "baseline", 2.5), _judgment(plan, "candidate", 4.0)
    forged = right.model_copy(
        update={"dimensions": (right.dimensions[0].model_copy(update={"score": True}), right.dimensions[1])}
    )
    assert assess_matched_pair(plan, "local", left, forged).status == "blocked"
    result = assess_matched_pair(plan, "local", left, right)
    for update in ({"decision": "baseline"}, {"candidate_score": 0.2}, {"execution_performed": True}):
        with pytest.raises(ValidationError):
            MatchedPairAssessment.model_validate(result.model_copy(update=update))


@pytest.mark.parametrize("field", ["rubric_id", "version_or_digest"])
def test_private_rubric_identifiers_reject_and_recovers(field: str) -> None:
    plan = _plan()
    raw = plan.model_dump(mode="json")
    raw["rubric"][field] = "token=private-value"
    left, right = _judgment(plan, "baseline", 2.5), _judgment(plan, "candidate", 4.0)
    result = assess_matched_pair(raw, "local", left, right)
    assert result.status == "blocked" and result.plan is None
    assert "private-value" not in result.model_dump_json()
    assert assess_matched_pair(plan, "local", left, right).status == "assessed"


def test_near_normalized_weights_cannot_exceed_score_range() -> None:
    plan = _plan()
    raw = plan.model_dump(mode="json")
    raw["rubric"]["dimensions"][0]["weight"] = 0.5000000001
    with pytest.raises(ValidationError):
        MatchedComparisonPlan.model_validate(raw)


def test_unknown_copied_fields_and_duplicate_refs_reject() -> None:
    plan = _plan()
    left, right = _judgment(plan, "baseline", 2.5), _judgment(plan, "candidate", 4.0)
    for updates in ({"unknown": "value"}, {"evidence_refs": ("evidence/judgment.json", "evidence/judgment.json")}):
        forged = right.model_copy(
            update={"dimensions": (right.dimensions[0].model_copy(update=updates), right.dimensions[1])}
        )
        assert assess_matched_pair(plan, "local", left, forged).status == "blocked"


def test_per_case_receipt_ids_are_retained_and_bound() -> None:
    original = _plan()
    raw = original.model_dump(mode="json")
    raw["case_bindings"][0]["baseline_scenario_set_id"] = "baseline-case-0-release"
    raw["case_bindings"][0]["candidate_scenario_set_id"] = "candidate-case-0-release"
    raw["baseline_scenarios"][0]["scenario_set_id"] = "baseline-case-0-release"
    raw["candidate_scenarios"][0]["scenario_set_id"] = "candidate-case-0-release"
    plan = MatchedComparisonPlan.model_validate(raw)
    left = _judgment(original, "baseline", 2.5).model_dump(mode="json")
    right = _judgment(original, "candidate", 4.0).model_dump(mode="json")
    assert assess_matched_pair(plan, "local", left, right).status == "blocked"
    left["evidence"]["scenario_set_id"] = "baseline-case-0-release"
    right["evidence"]["scenario_set_id"] = "candidate-case-0-release"
    result = assess_matched_pair(plan, "local", left, right)
    assert result.status == "assessed" and result.decision == "candidate"
    assert result.baseline.evidence.scenario_set_id != result.candidate.evidence.scenario_set_id


@pytest.mark.parametrize("change", ["omitted_child", "order", "child", "release", "reference"])
def test_whole_plugin_plan_closure_rejects_and_recovers(change: str) -> None:
    """Do not drop a child, swap case order or substitute a plugin for its driver."""
    plan = _plan()
    raw = plan.model_dump(mode="json")
    if change == "omitted_child":
        for case in raw["plugin_scope"]["cases"]:
            case["driver_skill_path"] = "skills/skill-0"
            for variant in ("baseline", "candidate"):
                case[f"{variant}_scorer"] = deepcopy(raw["plugin_scope"]["cases"][0][f"{variant}_scorer"])
            if case["scope"] == "per_skill":
                case["selected_skill_paths"] = ["skills/skill-0"]
    elif change == "order":
        raw["candidate_scenarios"][0], raw["candidate_scenarios"][1] = (
            raw["candidate_scenarios"][1],
            raw["candidate_scenarios"][0],
        )
    elif change == "child":
        raw["candidate_scenarios"][0]["candidate"] = plan.candidate.model_dump(mode="json")
    elif change == "release":
        raw["baseline_scenarios"][0]["release"] = True
    else:
        raw["plugin_scope"]["cases"][0]["reference_paths"] = ["references/unretained.md"]
    with pytest.raises(ValidationError):
        MatchedComparisonPlan.model_validate(raw)
    assert MatchedComparisonPlan.model_validate(plan) == plan


def test_reference_paths_bind_both_captures_before_coercion() -> None:
    """Common retained references pass, while padding and bytes cannot become paths."""
    plan = _plan()
    raw = plan.model_dump(mode="json")
    raw["plugin_scope"]["cases"][0]["reference_paths"] = ["skills/skill-0/SKILL.md"]
    bound = MatchedComparisonPlan.model_validate(raw)
    for path in (" skills/skill-0/SKILL.md ", b"skills/skill-0/SKILL.md"):
        changed = deepcopy(raw)
        changed["plugin_scope"]["cases"][0]["reference_paths"] = [path]
        with pytest.raises(ValidationError):
            MatchedComparisonPlan.model_validate(changed)
    assert MatchedComparisonPlan.model_validate(bound) == bound


def test_one_variant_only_reference_cannot_enter_case_scope() -> None:
    """Actual captured baseline-only bytes are not shared reference evidence."""
    with TemporaryDirectory(prefix="matched-reference-fixture-") as directory:
        root = Path(directory).resolve()
        scope = _fixture(root, count=2)
        reference = root / "baseline" / "references" / "review.md"
        reference.parent.mkdir()
        reference.write_text("# Synthetic review reference\n", encoding="utf-8")
        captured = validate_plugin_package(root / "baseline", source_revision="1" * 40)
        assert captured.status == "pass"
        scope["baseline"] = captured.model_dump(mode="json")
        scope["baseline_coverage"]["candidate"] = captured.candidate.model_dump(mode="json")
    raw = _plan().model_dump(mode="json")
    for case in scope["cases"]:
        for variant in ("baseline", "candidate"):
            case[f"{variant}_scorer"]["calibration_probe_ids"] = [f"probe-{index}" for index in range(6)]
    raw["plugin_scope"] = scope
    good = MatchedComparisonPlan.model_validate(raw)
    raw["plugin_scope"]["cases"][0]["reference_paths"] = ["references/review.md"]
    with pytest.raises(ValidationError, match="both complete variant captures"):
        MatchedComparisonPlan.model_validate(raw)
    assert MatchedComparisonPlan.model_validate(good) == good


@pytest.mark.parametrize("value", [0, "false"])
@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
def test_release_flag_cannot_coerce_nonboolean_input(value: object, form: str) -> None:
    """Matched strict ingress and packaged schema agree without changing ScenarioSetV2."""
    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry

    plan = _plan()
    raw = plan.model_dump(mode="json")
    raw["baseline_scenarios"][0]["release"] = value
    candidate = raw
    if form == "copy":
        candidate = plan.model_copy(update={"baseline_scenarios": raw["baseline_scenarios"]})
    elif form == "construct":
        candidate = MatchedComparisonPlan.model_construct(**raw)
    with pytest.raises(ValidationError):
        if form == "json":
            MatchedComparisonPlan.model_validate_json(json.dumps(raw))
        else:
            MatchedComparisonPlan.model_validate(candidate)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-comparison-plan.v1", raw)
    assert MatchedComparisonPlan.model_validate(plan) == plan


@pytest.mark.parametrize("field", ["calibration_required", "deterministic_checks_first"])
@pytest.mark.parametrize("value", [1, "true"])
def test_matched_scorer_boolean_siblings_are_also_strict(field: str, value: object) -> None:
    """Reject coercible flags throughout the new boundary without freezing new legacy behaviour."""
    plan = _plan()
    raw = plan.model_dump(mode="json")
    raw["plugin_scope"]["cases"][0]["baseline_scorer"][field] = value
    with pytest.raises(ValidationError, match="Boolean"):
        MatchedComparisonPlan.model_validate(raw)
    assert MatchedComparisonPlan.model_validate(plan) == plan
