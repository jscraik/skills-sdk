"""Frozen private input commitments and sequential first-stop observations."""

from __future__ import annotations

import asyncio
from collections import UserDict
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_matched_comparison import _judgment, _plan
from test_matched_execution import _matched

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import execute_matched_lane, prepare_matched_cloud_handoff
from skills_sdk.models import MatchedCalibrationReceipt, MatchedExecutionReceipt, MatchedVariantJudgment
from skills_sdk.models.matched_calibration import _dimension_digest
from skills_sdk.models.matched_execution import _require_selected_result


def test_variant_input_digests_reject_tampering_and_recover(tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    registry = SchemaRegistry()
    for field in ("baseline_input_sha256", "candidate_input_sha256"):
        changed = receipt.model_dump(mode="json")
        changed["pairs"][0][field] = "e" * 64
        with pytest.raises(ValidationError, match="frozen variant input"):
            MatchedExecutionReceipt.model_validate(changed)
        with pytest.raises(ContractError):
            registry.validate("matched-execution.v1", changed)
        forged = receipt.model_copy(
            update={"pairs": (receipt.pairs[0].model_copy(update={field: "e" * 64}), *receipt.pairs[1:])}
        )
        with pytest.raises(ValidationError):
            MatchedExecutionReceipt.model_validate(forged)
        declaration = plan.model_dump(mode="json")
        declaration["case_bindings"][0][field] = "e" * 64
        events.clear()
        blocked = asyncio.run(execute_matched_lane(declaration, "local", calibrations, batch))
        assert blocked.status == "blocked" and blocked.provider_invocation_count == 0 and not events
    registry.validate("matched-execution.v1", receipt.model_dump(mode="json"))
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"
    target_receipt = calibrations[0].targets[0].receipt
    for missing in ("rubric", "calibration"):
        raw = target_receipt.model_dump(mode="json")
        raw.update(
            status="blocked", judgments=[], blocker={"code": "invalid_matched_calibration", "message": "Blocked."}
        )
        raw[missing] = None
        with pytest.raises(ValidationError, match="partial execution"):
            MatchedCalibrationReceipt.model_validate(raw)
        with pytest.raises(ContractError):
            registry.validate("matched-calibration.v1", raw)
    assert MatchedCalibrationReceipt.model_validate(target_receipt).status == "pass"


def test_first_stop_requires_baseline_judge_before_candidate_provider(tmp_path: Path) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    raw = receipt.model_dump(mode="json")
    raw.update(
        status="blocked",
        pairs=[],
        provider_invocation_count=2,
        judge_invocation_count=0,
        blocker={"code": "matched_execution_incomplete", "message": "Blocked."},
    )
    with pytest.raises(ValidationError, match="preceding baseline judge"):
        MatchedExecutionReceipt.model_validate(raw)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-execution.v1", raw)
    for providers, judges in ((0, 0), (1, 0), (1, 1), (2, 1), (2, 2)):
        neighbour = dict(raw, provider_invocation_count=providers, judge_invocation_count=judges)
        assert MatchedExecutionReceipt.model_validate(neighbour).status == "blocked"
    assert MatchedExecutionReceipt.model_validate(receipt).status == "completed"


def test_selected_result_metadata_and_semantic_membership_recover(tmp_path: Path) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    for updates in (
        {"runner_id": "token=private-value"},
        {"runner_version_or_digest": "wrong-version"},
        {"evidence_refs": ["evidence/token=private-value"]},
        {"expected_output_sha256": receipt.pairs[0].candidate.evidence.output_sha256},
        {"output_digest_mismatch": True},
    ):
        raw = receipt.model_dump(mode="json")
        raw["pairs"][0]["candidate_evaluation"]["case_results"][0].update(updates)
        with pytest.raises(ValidationError):
            MatchedExecutionReceipt.model_validate(raw)
        with pytest.raises(ContractError):
            SchemaRegistry().validate("matched-execution.v1", raw)
        pair = receipt.pairs[0]
        evaluation = pair.candidate_evaluation
        forged = receipt.model_copy(
            update={
                "pairs": (
                    pair.model_copy(
                        update={
                            "candidate_evaluation": evaluation.model_copy(
                                update={"case_results": (evaluation.case_results[0].model_copy(update=updates),)}
                            )
                        }
                    ),
                    *receipt.pairs[1:],
                )
            }
        )
        with pytest.raises(ValidationError):
            MatchedExecutionReceipt.model_validate(forged)
    raw = receipt.model_dump(mode="json")
    judgment = raw["pairs"][0]["candidate"]
    judgment["evidence"]["satisfied_assertion_ids"] = ["undeclared"]
    digest = _dimension_digest(plan.rubric, MatchedVariantJudgment.model_validate(judgment))
    judgment["evidence"]["judge_result_sha256"] = digest
    judgment["evidence"]["evidence_refs"] = [
        ref for ref in judgment["evidence"]["evidence_refs"] if not ref.startswith("judge-results/")
    ] + [f"judge-results/{digest}"]
    with pytest.raises(ValidationError, match="undeclared semantic"):
        MatchedExecutionReceipt.model_validate(raw)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-execution.v1", raw)
    declaration = plan.model_dump(mode="json")
    declaration["case_bindings"][0]["semantic_signal_ids"] = []
    events = batch[0].baseline.judge.events
    events.clear()
    blocked = asyncio.run(execute_matched_lane(declaration, "local", calibrations, batch))
    assert blocked.status == "blocked" and blocked.provider_invocation_count == 0 and not events
    pair = receipt.pairs[0]
    judge = pair.candidate.evidence.judge.model_copy(update={"adapter_id": "separate-judge"})
    distinct = pair.candidate.model_copy(
        update={"evidence": pair.candidate.evidence.model_copy(update={"judge": judge})}
    )
    result = pair.candidate_evaluation.case_results[0].model_copy(update={"runner_id": judge.adapter_id})
    _require_selected_result(distinct, pair.candidate_evaluation.model_copy(update={"case_results": (result,)}))
    with pytest.raises(ValueError, match="actual judge runner"):
        _require_selected_result(distinct, pair.candidate_evaluation)
    assert MatchedExecutionReceipt.model_validate(receipt).status == "completed"


def test_noncanonical_mapping_cannot_launder_copied_unknown_members() -> None:
    plan = _plan()
    judgment = _judgment(plan, "baseline", 2.5)
    raw = judgment.model_dump(mode="python")
    raw["evidence"] = UserDict(
        dict(judgment.evidence.model_dump(mode="python"), candidate=plan.baseline.model_copy(update={"unknown": "x"}))
    )
    with pytest.raises(ValidationError, match="canonical dictionary"):
        MatchedVariantJudgment.model_validate(raw)
    assert MatchedVariantJudgment.model_validate(judgment) == judgment
    assert MatchedVariantJudgment.model_validate(judgment.model_dump(mode="json")) == judgment


def test_executed_scorer_and_confidence_cannot_be_relabelled(tmp_path: Path) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    raw = receipt.model_dump(mode="json")
    evidence = raw["pairs"][0]["candidate"]["evidence"]
    evidence["evidence_refs"] = [ref for ref in evidence["evidence_refs"] if not ref.startswith("judge-results/")] + [
        f"judge-results/{'e' * 64}"
    ]
    with pytest.raises(ValidationError, match="result reference"):
        MatchedExecutionReceipt.model_validate(raw)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-execution.v1", raw)
    for updates in (
        {"scorer_id": "token=private-value"},
        {"version_or_digest": "not-selected-case"},
        {"calibration_required": True, "calibration_probe_ids": ["other-probe"]},
    ):
        raw = receipt.model_dump(mode="json")
        evaluation = raw["pairs"][0]["candidate_evaluation"]
        evaluation["scorer"].update(updates)
        if updates.get("calibration_required"):
            evaluation["completed_calibration_probe_ids"] = ["other-probe"]
        with pytest.raises(ValidationError):
            MatchedExecutionReceipt.model_validate(raw)
        with pytest.raises(ContractError):
            SchemaRegistry().validate("matched-execution.v1", raw)
    raw = receipt.model_dump(mode="json")
    for pair in raw["pairs"]:
        for variant in ("baseline", "candidate"):
            judgment = pair[variant]
            judgment["confidence"] = "low"
            digest = _dimension_digest(plan.rubric, MatchedVariantJudgment.model_validate(judgment))
            evidence = judgment["evidence"]
            evidence["judge_result_sha256"] = digest
            evidence["evidence_refs"] = [
                ref for ref in evidence["evidence_refs"] if not ref.startswith("judge-results/")
            ] + [f"judge-results/{digest}"]
    with pytest.raises(ValidationError, match="confidence"):
        MatchedExecutionReceipt.model_validate(raw)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-execution.v1", raw)
    assert prepare_matched_cloud_handoff(raw, plan).status == "blocked"
    assert MatchedExecutionReceipt.model_validate(receipt).status == "completed"
