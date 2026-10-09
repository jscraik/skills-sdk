"""Actual local selection, cloud baseline reuse, rejection and recovery."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_matched_execution import _matched

from skills_sdk.evaluation.matched_execution import execute_matched_lane
from skills_sdk.evaluation.matched_handoff import execute_matched_cloud, prepare_matched_cloud_handoff
from skills_sdk.models.matched_handoff import MatchedCloudExecutionReceipt, MatchedCloudHandoff


def _journey(root: Path, local_candidate_score: float = 4.5) -> tuple[object, object, object, object, list[str]]:
    local_root, cloud_root = root / "local", root / "cloud"
    local_root.mkdir()
    cloud_root.mkdir()
    local_plan, calibrations, batch, _ = _matched(local_root, trials=2, variants=(2.5, local_candidate_score, "local"))
    local = asyncio.run(execute_matched_lane(local_plan, "local", calibrations, batch))
    plan, calibrations, batch, events = _matched(cloud_root, variants=(local_candidate_score, 5.0, "cloud"))
    return local, plan, calibrations, batch, events


def test_actual_local_winner_becomes_cloud_baseline(tmp_path: Path) -> None:
    local, plan, calibrations, batch, events = _journey(tmp_path)
    handoff = prepare_matched_cloud_handoff(local, plan)
    assert handoff.status == "ready" and handoff.cloud_plan.baseline == local.plan.candidate
    assert MatchedCloudHandoff.model_validate_json(handoff.model_dump_json()) == handoff
    result = asyncio.run(execute_matched_cloud(handoff, calibrations, batch))
    assert result.status == "completed" and result.execution.lane == "cloud" and len(result.execution.pairs) == 10
    assert result.execution.provider_invocation_count == result.execution.judge_invocation_count == 20
    assert events.count("provider") == events.count("dimensional_judge") == 20
    assert result.execution.plan.baseline == local.plan.candidate
    assert result.handoff == handoff
    assert MatchedCloudExecutionReceipt.model_validate_json(result.model_dump_json()) == result
    for updates in ({"handoff": None, "handoff_sha256": None}, {"handoff_sha256": "e" * 64}, {"status": "blocked"}):
        with pytest.raises(ValidationError):
            MatchedCloudExecutionReceipt.model_validate(result.model_copy(update=updates))


def test_exact_threshold_local_lift_is_eligible(tmp_path: Path) -> None:
    local, plan, _, _, _ = _journey(tmp_path, local_candidate_score=3.0)
    assert all(local.comparison(index).decision == "candidate" for index in range(10))
    assert prepare_matched_cloud_handoff(local, plan).status == "ready"


@pytest.mark.parametrize("change", ["baseline", "rubric", "assertions", "digest", "promotion"])
def test_changed_handoff_rejects_without_capability_access_then_recovers(change: str, tmp_path: Path) -> None:
    local, plan, calibrations, batch, events = _journey(tmp_path)
    handoff = prepare_matched_cloud_handoff(local, plan)
    raw = handoff.model_dump(mode="json")
    if change == "baseline":
        raw["cloud_plan"] = local.plan.model_dump(mode="json")
    elif change == "rubric":
        raw["cloud_plan"]["rubric"]["dimensions"][0]["criterion"] = "A different objective."
    elif change == "assertions":
        raw["cloud_plan"]["case_bindings"][0]["assertion_contract_sha256"] = "e" * 64
    elif change == "digest":
        raw["local_receipt_sha256"] = "e" * 64
    else:
        raw["promotion_authorized"] = True
    with pytest.raises(ValidationError):
        MatchedCloudHandoff.model_validate(raw)

    class Trap:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"premature cloud access: {name}")

    guarded = tuple(
        replace(pair, baseline=replace(pair.baseline, provider=Trap()), candidate=replace(pair.candidate, judge=Trap()))
        for pair in batch
    )
    blocked = asyncio.run(execute_matched_cloud(raw, calibrations, guarded))
    assert blocked.status == "blocked" and blocked.execution.provider_invocation_count == 0 and not events
    assert asyncio.run(execute_matched_cloud(handoff, calibrations, batch)).status == "completed"


def test_no_local_lift_blocks_cloud_selection(tmp_path: Path) -> None:
    local_root, cloud_root = tmp_path / "local", tmp_path / "cloud"
    local_root.mkdir()
    cloud_root.mkdir()
    plan, calibrations, batch, _ = _matched(local_root, variants=(4.5, 4.6, "local"))
    local = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    cloud, _, _, _ = _matched(cloud_root, variants=(4.6, 5.0, "cloud"))
    result = prepare_matched_cloud_handoff(local, cloud)
    assert result.status == "blocked" and result.blocker.code == "invalid_matched_handoff"
    assert MatchedCloudHandoff.model_validate_json(result.model_dump_json()) == result


def test_local_regression_blocks_handoff_and_corrected_execution_recovers(tmp_path: Path) -> None:
    local_root, cloud_root = tmp_path / "local", tmp_path / "cloud"
    local_root.mkdir()
    cloud_root.mkdir()
    plan, calibrations, batch, _ = _matched(local_root, trials=2)
    cloud, _, _, _ = _matched(cloud_root, variants=(4.5, 5.0, "cloud"))
    batch[0].candidate.provider.text = "behavior preserved; rm -rf"
    failed = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert failed.status == "completed" and failed.requires_regression
    assert prepare_matched_cloud_handoff(failed, cloud).status == "blocked"
    batch[0].candidate.provider.text = "behavior preserved"
    corrected = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert prepare_matched_cloud_handoff(corrected, cloud).status == "ready"


def test_blocked_cloud_batch_retains_handoff_and_recovers(tmp_path: Path) -> None:
    local, plan, calibrations, batch, events = _journey(tmp_path)
    handoff = prepare_matched_cloud_handoff(local, plan)
    blocked = asyncio.run(execute_matched_cloud(handoff, calibrations, batch[:-1]))
    assert blocked.status == "blocked" and blocked.handoff == handoff
    assert blocked.execution.provider_invocation_count == 0 and not events
    assert MatchedCloudExecutionReceipt.model_validate_json(blocked.model_dump_json()) == blocked
    completed = asyncio.run(execute_matched_cloud(handoff, calibrations, batch))
    assert completed.status == "completed" and completed.handoff_sha256 == blocked.handoff_sha256


def test_cloud_receipt_cannot_swap_in_local_execution_or_copied_unknowns(tmp_path: Path) -> None:
    local, plan, calibrations, batch, _ = _journey(tmp_path)
    handoff = prepare_matched_cloud_handoff(local, plan)
    completed = asyncio.run(execute_matched_cloud(handoff, calibrations, batch))
    with pytest.raises(ValidationError, match="frozen cloud plan"):
        MatchedCloudExecutionReceipt.model_validate(completed.model_copy(update={"execution": local}))
    with pytest.raises(ValidationError, match="unknown fields"):
        MatchedCloudExecutionReceipt.model_validate(
            completed.model_copy(update={"handoff": handoff.model_copy(update={"extra_clearance": True})})
        )
    assert MatchedCloudExecutionReceipt.model_validate(completed).status == "completed"
