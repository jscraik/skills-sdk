"""Plan/runtime agreement, frozen recovery controls and actionable CLI blockers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from test_matched_comparison import _plan
from test_matched_feedback import _failure

from skills_sdk.cli.main import main
from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import execute_matched_lane, execute_matched_regression
from skills_sdk.evaluation.matched_plugin_context import PluginExecutionContext, _validated_paths
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.models.matched_feedback import MatchedRegressionReceipt
from skills_sdk.models.matched_plugin_calibration import MatchedVariantCalibrationBundle
from skills_sdk.models.matched_plugin_scope import MatchedPluginCaseScope


@pytest.mark.parametrize(
    "reference",
    [
        "skills/skill-0/references/evals.yaml",
        "skills/skill-0/SKILL.md",
        "references/hidden-guide.md",
        "references/SCORER.md",
        "calibration/guide.markdown",
        "references/guide.txt",
    ],
)
@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
def test_plan_reference_eligibility_matches_runtime(reference: str, form: str) -> None:
    good = _plan().plugin_scope.cases[0]
    raw = good.model_dump(mode="json")
    raw["reference_paths"] = [reference]
    value = raw
    if form == "copy":
        value = good.model_copy(update={"reference_paths": (reference,)})
    elif form == "construct":
        value = MatchedPluginCaseScope.model_construct(**raw)
    context = PluginExecutionContext(
        Path("unused"),
        _plan().plugin_scope.baseline,
        good.driver_skill_path,
        good.selected_skill_paths,
        (reference,),
    )
    with pytest.raises((ValueError, ContractError)):
        _validated_paths(context)
    with pytest.raises(ValueError):
        if form == "json":
            MatchedPluginCaseScope.model_validate_json(json.dumps(raw))
        else:
            MatchedPluginCaseScope.model_validate(value)
    assert MatchedPluginCaseScope.model_validate(good) == good


@pytest.mark.parametrize(
    "reference", ["README.md", "references/SKILL.md", "references/shared.markdown", "skills/skill-0/guide.MD"]
)
def test_ordinary_reference_neighbours_remain_eligible(reference: str) -> None:
    plan = _plan()
    case = plan.plugin_scope.cases[0].model_copy(update={"reference_paths": (reference,)})
    assert MatchedPluginCaseScope.model_validate(case) == case
    context = PluginExecutionContext(
        Path("unused"),
        plan.plugin_scope.baseline,
        case.driver_skill_path,
        case.selected_skill_paths,
        (reference,),
    )
    assert _validated_paths(context) == (reference,)


def test_nested_plan_and_registry_reject_automatic_entrypoint_then_recover() -> None:
    good = _plan()
    raw = good.model_dump(mode="json")
    raw["plugin_scope"]["cases"][0]["reference_paths"] = ["skills/skill-0/SKILL.md"]
    for value in (raw, good.model_copy(update={"plugin_scope": raw["plugin_scope"]})):
        with pytest.raises(ValueError):
            MatchedComparisonPlan.model_validate(value)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-comparison-plan.v1", raw)
    SchemaRegistry().validate("matched-comparison-plan.v1", good.model_dump(mode="json"))


def test_recovery_keeps_passing_baseline_calibration_frozen(tmp_path: Path) -> None:
    failed, plan, calibrations, batch, events = _failure(tmp_path)
    owners = ({"case_id": "case-0", "owner": "SDK maintainer"},)
    batch[0].candidate.provider.text = "behavior preserved"
    raw_bundle = calibrations[0].model_dump(mode="json")
    raw_bundle["targets"][0]["receipt"]["calibration"]["plan"]["policy"]["max_false_positives"] = 1
    changed_bundle = MatchedVariantCalibrationBundle.model_validate(raw_bundle)
    assert changed_bundle.targets[0].receipt.status == "pass"
    raw_plan = plan.model_dump(mode="json")
    raw_plan["lanes"][0]["baseline_calibration_sha256"] = canonical_json_sha256(raw_bundle)
    changed = MatchedComparisonPlan.model_validate(raw_plan)
    rejected = asyncio.run(
        execute_matched_regression(failed, owners, changed, (changed_bundle, calibrations[1]), batch)
    )
    assert rejected.status == "blocked" and rejected.rerun is None and not events
    assert rejected.blocker.code == "invalid_matched_feedback"
    recovered = asyncio.run(execute_matched_regression(failed, owners, plan, calibrations, batch))
    assert recovered.status == "closed"
    separate = asyncio.run(execute_matched_lane(changed, "local", (changed_bundle, calibrations[1]), batch))
    assert separate.status == "completed"
    forged = recovered.model_dump(mode="json")
    forged["rerun"] = separate.model_dump(mode="json")
    with pytest.raises(ValueError, match="baseline calibration"):
        MatchedRegressionReceipt.model_validate(forged)
    with pytest.raises(ContractError) as rejected_receipt:
        SchemaRegistry().validate("matched-regression.v1", forged)
    assert rejected_receipt.value.code == "contract_validation_failed"
    assert any("baseline calibration" in detail for detail in rejected_receipt.value.details)


def test_cloud_regression_text_emits_nested_blocker(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "invalid.json"
    source.write_text("{}", encoding="utf-8")
    command = ["eval", "matched-cloud-regression", "--input", str(source), "--adapter-mode", "supplied-offline"]
    assert main([*command, "--json"]) == 2
    receipt = json.loads(capsys.readouterr().out)
    blocker = receipt["feedback"]["blocker"]
    assert main(command) == 2
    text = capsys.readouterr().out
    assert "matched-cloud-regression: blocked" in text
    assert f"{blocker['code']}: {blocker['message']}" in text
