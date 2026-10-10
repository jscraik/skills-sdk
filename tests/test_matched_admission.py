"""Executed calibration admission and whole-batch rejection before host access."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_live_selected_case import _Provider
from test_matched_calibration import DimensionJudge
from test_matched_comparison import _plan
from test_matched_execution import _matched
from test_selected_case_evaluation import _safety_for

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.evaluation.matched_admission import _require_calibration, preflight_matched_lane
from skills_sdk.evaluation.matched_calibration import execute_matched_calibration
from skills_sdk.evaluation.observed_calibration import CalibrationProbeExecution
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.evaluation.skill_context import prepare_selected_case_context
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.models.matched_plugin_calibration import MatchedVariantCalibrationBundle
from skills_sdk.models.observed_calibration import ObservedCalibrationPlan


def _calibrated(root: Path, count: int = 6) -> tuple[MatchedComparisonPlan, MatchedVariantCalibrationBundle, list[str]]:
    """Obtain actual controlled callbacks; never invent an executed receipt."""
    plan, bundles, batch, events = _matched(root)
    bundle = bundles[0]
    if count == 6:
        return plan, bundle, events
    target = bundle.targets[0]
    calibration = target.receipt.calibration.plan
    texts = tuple(f"held-out output {index}" for index in range(count))
    raw = calibration.model_dump(mode="json")
    ids = [f"probe-{index}" for index in range(count)]
    raw["scorer"]["calibration_probe_ids"] = ids
    raw["policy"]["minimum_examples"] = count
    raw["probes"] = [
        {
            "probe_id": identifier,
            "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "expected_label": "pass" if index % 2 == 0 else "fail",
        }
        for index, (identifier, text) in enumerate(zip(ids, texts, strict=True))
    ]
    calibration = ObservedCalibrationPlan.model_validate(raw)
    frame = batch[0].baseline
    payload = prepare_selected_case_context(frame.definition)
    request = frame.request.model_copy(update={"input_sha256": canonical_json_sha256(payload)})
    inputs = SelectedCaseExecutionInput(payload, _safety_for(frame.definition, request))
    executions = tuple(
        CalibrationProbeExecution(
            frame.definition,
            request,
            inputs,
            _Provider(request, events, text),
            DimensionJudge(
                SimpleNamespace(
                    identity=calibration.judge,
                    parameters=calibration.parameters,
                    definition=frame.definition,
                    request=request,
                ),
                4.5 if index % 2 == 0 else 0.5,
                events,
            ),
        )
        for index, text in enumerate(texts)
    )
    events.clear()
    receipt = asyncio.run(execute_matched_calibration(calibration, plan.rubric, executions))
    assert receipt.status == "pass" and events.count("dimensional_judge") == 2 * count
    incomplete = target.model_copy(update={"receipt": receipt, "scorer": calibration.scorer})
    return plan, bundle.model_copy(update={"targets": (incomplete, *bundle.targets[1:])}), events


def test_observed_calibration_binds_before_matched_execution(tmp_path: Path) -> None:
    plan, receipt, _ = _calibrated(tmp_path)
    _require_calibration(plan, plan.lanes[0], "baseline", receipt)
    target = receipt.targets[0]
    observed = target.receipt.calibration.model_copy(update={"judge_invocation_count": 0})
    forged_target = target.model_copy(update={"receipt": target.receipt.model_copy(update={"calibration": observed})})
    forged = receipt.model_copy(update={"targets": (forged_target, *receipt.targets[1:])})
    with pytest.raises(ValueError):
        _require_calibration(plan, plan.lanes[0], "baseline", forged)
    _require_calibration(plan, plan.lanes[0], "baseline", receipt)


@pytest.mark.parametrize("change", ["digest", "judge", "settings", "candidate"])
def test_changed_calibration_commitments_reject_and_recover(tmp_path: Path, change: str) -> None:
    plan, receipt, _ = _calibrated(tmp_path)
    raw = plan.model_dump(mode="json")
    if change == "digest":
        raw["lanes"][0]["baseline_calibration_sha256"] = "0" * 64
    elif change == "judge":
        raw["lanes"][0]["judge"]["adapter_version_or_digest"] = "changed"
    elif change == "settings":
        raw["lanes"][0]["judge_parameters"]["temperature"] = 0.2
    else:
        capture = raw["plugin_scope"]["baseline"]
        capture["candidate"]["source_revision"] = "3" * 40
        for child in capture["skills"]:
            child["validation"]["candidate"]["source_revision"] = "3" * 40
        for case, scenario in zip(raw["plugin_scope"]["cases"], raw["baseline_scenarios"], strict=True):
            case["baseline_scorer"]["candidate"]["source_revision"] = "3" * 40
            scenario["candidate"]["source_revision"] = "3" * 40
        raw["plugin_scope"]["baseline_coverage"]["candidate"] = capture["candidate"]
    changed = MatchedComparisonPlan.model_validate(raw)
    with pytest.raises(ValueError):
        _require_calibration(changed, changed.lanes[0], "baseline", receipt)
    _require_calibration(plan, plan.lanes[0], "baseline", receipt)


def test_two_probe_calibration_is_not_full_scorer_quality_coverage(tmp_path: Path) -> None:
    plan, receipt, _ = _calibrated(tmp_path, count=2)
    with pytest.raises(ValueError, match="held-out coverage"):
        _require_calibration(plan, plan.lanes[0], "baseline", receipt)


def test_missing_calibration_blocks_without_inspecting_host_batch() -> None:
    class UnreadableBatch:
        def __iter__(self) -> object:
            raise AssertionError("host batch must not be accessed")

    blocker = preflight_matched_lane(_plan(), "local", (None, None), UnreadableBatch())
    assert blocker is not None and blocker.code == "invalid_matched_execution"
