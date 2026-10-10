"""Receipt gates reuse bound pair scores without rebuilding public assessments."""

from __future__ import annotations

import asyncio
from copy import copy
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_matched_execution import _matched
from test_matched_handoff import _journey

from skills_sdk.evaluation.matched_admission import MatchedCaseExecution, MatchedTrialAdapters, MatchedVariantExecution
from skills_sdk.evaluation.matched_execution import execute_matched_lane
from skills_sdk.evaluation.matched_feedback import execute_matched_regression
from skills_sdk.evaluation.matched_handoff import prepare_matched_cloud_handoff
from skills_sdk.models import matched_execution
from skills_sdk.models.matched_feedback import MatchedRegressionReceipt, _failed_case_ids
from skills_sdk.models.matched_handoff import MatchedCloudHandoff


def _forbid_public_assessments(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_assessment(**values: object) -> object:
        raise AssertionError("receipt gate must not reconstruct a public pair assessment")

    monkeypatch.setattr(matched_execution, "MatchedPairAssessment", unexpected_assessment)


def _fresh_feedback_batch(batch: tuple[MatchedCaseExecution, ...], text: str) -> tuple[MatchedCaseExecution, ...]:
    """Copy resource-free fixture adapters, preserving source bindings and event sinks."""

    def fresh(variant: MatchedVariantExecution) -> MatchedVariantExecution:
        return replace(
            variant,
            provider=copy(variant.provider),
            judge=copy(variant.judge),
            additional_trials=tuple(
                MatchedTrialAdapters(copy(trial.provider), copy(trial.judge)) for trial in variant.additional_trials
            ),
        )

    frames = tuple(replace(frame, baseline=fresh(frame.baseline), candidate=fresh(frame.candidate)) for frame in batch)
    candidate = frames[-1].candidate
    for provider in (candidate.provider, *(trial.provider for trial in candidate.additional_trials)):
        provider.text = text
    return frames


def test_handoff_roundtrip_avoids_pair_assessments_and_retains_ingress_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local, plan, _, _, _ = _journey(tmp_path)
    handoff = prepare_matched_cloud_handoff(local, plan)
    assert handoff.status == "ready" and len(local.pairs) >= 20
    _forbid_public_assessments(monkeypatch)
    assert MatchedCloudHandoff.model_validate_json(handoff.model_dump_json()) == handoff
    forged = local.plan.model_copy(update={"unverified_clearance": True})
    changed = handoff.model_copy(update={"local": local.model_copy(update={"plan": forged})})
    with pytest.raises(ValidationError, match="unknown fields"):
        MatchedCloudHandoff.model_validate(changed)
    assert MatchedCloudHandoff.model_validate(handoff) == handoff


@pytest.mark.parametrize(
    ("score", "decision", "regression"),
    [(4.5, "candidate", False), (2.5, "inconclusive", False), (2.25, "inconclusive", True), (1.0, "baseline", True)],
)
def test_lightweight_regression_matches_public_assessment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, score: float, decision: str, regression: bool
) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    candidate = batch[-1].candidate
    for judge in (candidate.judge, *(trial.judge for trial in candidate.additional_trials)):
        judge.score = score
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    indexes = [index for index, pair in enumerate(receipt.pairs) if pair.case_id == candidate.request.case_id]
    assert len(indexes) == 1 + len(candidate.additional_trials)
    for index in indexes:
        assessment = receipt.comparison(index)
        assert assessment.decision == decision and assessment.regression_required is regression
    _forbid_public_assessments(monkeypatch)
    assert receipt.requires_regression is regression
    assert _failed_case_ids(receipt) == ((batch[-1].candidate.request.case_id,) if regression else ())


def test_feedback_roundtrip_avoids_pair_assessments_and_preserves_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    failed_batch = _fresh_feedback_batch(batch, "behavior preserved; rm -rf")
    failed = asyncio.run(execute_matched_lane(plan, "local", calibrations, failed_batch))
    case_id = batch[-1].candidate.request.case_id
    failed_pairs = tuple(pair for pair in failed.pairs if pair.case_id == case_id)
    assert len(failed_pairs) == 1 + len(batch[-1].candidate.additional_trials)
    assert all(pair.candidate_evaluation.status == "fail" for pair in failed_pairs) and failed.requires_regression
    _forbid_public_assessments(monkeypatch)
    owners = ({"case_id": case_id, "owner": "SDK evaluation maintainer"},)
    still_failing = _fresh_feedback_batch(batch, "behavior preserved; rm -rf")
    opened = asyncio.run(execute_matched_regression(failed, owners, plan, calibrations, still_failing))
    assert opened.status == "open"
    assert MatchedRegressionReceipt.model_validate_json(opened.model_dump_json()) == opened
    corrected = _fresh_feedback_batch(batch, "behavior preserved")
    closed = asyncio.run(execute_matched_regression(failed, owners, plan, calibrations, corrected))
    assert closed.status == "closed" and not closed.rerun.requires_regression
    assert all(pair.candidate_evaluation.status == "pass" for pair in closed.rerun.pairs if pair.case_id == case_id)
    assert MatchedRegressionReceipt.model_validate_json(closed.model_dump_json()) == closed
    with pytest.raises(ValidationError, match="assign every failed case"):
        MatchedRegressionReceipt.model_validate(closed.model_copy(update={"assignments": ()}))
    assert MatchedRegressionReceipt.model_validate(closed) == closed
