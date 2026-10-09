"""Public exports and packaged structural/semantic matched-contract boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_matched_feedback import _failure
from test_matched_handoff import _journey

from skills_sdk import evaluation, models
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry


def test_public_services_are_callable_without_adapter_discovery() -> None:
    for name in (
        "assess_matched_pair",
        "execute_matched_calibration",
        "execute_matched_lane",
        "prepare_selected_case_context",
        "prepare_matched_cloud_handoff",
        "execute_matched_cloud",
        "execute_matched_regression",
        "execute_matched_cloud_regression",
        "MatchedCaseExecution",
        "MatchedVariantExecution",
        "DimensionalJudgeAdapter",
        "DimensionalJudgeInput",
    ):
        assert name in evaluation.__all__ and callable(getattr(evaluation, name))


def test_registered_matched_contracts_reject_semantic_tampering_and_recover(tmp_path: Path) -> None:
    journey_root, feedback_root = tmp_path / "journey", tmp_path / "feedback"
    journey_root.mkdir()
    feedback_root.mkdir()
    local, plan, calibrations, batch, _ = _journey(journey_root)
    handoff = evaluation.prepare_matched_cloud_handoff(local, plan)
    cloud = asyncio.run(evaluation.execute_matched_cloud(handoff, calibrations, batch))
    batch[0].candidate.provider.text = "behavior preserved; rm -rf"
    cloud_failure = asyncio.run(evaluation.execute_matched_cloud(handoff, calibrations, batch))
    batch[0].candidate.provider.text = "behavior preserved"
    cloud_feedback = asyncio.run(
        evaluation.execute_matched_cloud_regression(
            cloud_failure, ({"case_id": "case-0", "owner": "SDK maintainer"},), plan, calibrations, batch
        )
    )
    assert cloud_feedback.status == "closed" and cloud_feedback.handoff.local == local
    assert models.MatchedCloudRegressionReceipt.model_validate_json(cloud_feedback.model_dump_json()) == cloud_feedback
    failed, recovery_plan, recovery_calibrations, recovery_batch, _ = _failure(feedback_root)
    recovery_batch[0].candidate.provider.text = "behavior preserved"
    feedback = asyncio.run(
        evaluation.execute_matched_regression(
            failed,
            ({"case_id": "case-0", "owner": "SDK maintainer"},),
            recovery_plan,
            recovery_calibrations,
            recovery_batch,
        )
    )
    contracts = (
        ("matched-comparison-plan.v1", local.plan),
        ("matched-pair-assessment.v1", local.comparison(0)),
        ("matched-calibration.v1", local.calibrations[0].targets[0].receipt),
        ("matched-execution.v1", local),
        ("matched-cloud-handoff.v1", handoff),
        ("matched-cloud-execution.v1", cloud),
        ("matched-regression.v1", feedback),
        ("matched-cloud-regression.v1", cloud_feedback),
    )
    registry = SchemaRegistry()
    for name, contract in contracts:
        model = getattr(models, type(contract).__name__)
        assert type(contract).__name__ in models.__all__ and model is type(contract)
        raw = contract.model_dump(mode="json")
        validator = Draft202012Validator(registry.load(name))
        validator.validate(raw)
        registry.validate(name, raw)
        assert model.model_validate(raw) == contract
        changed = contract.model_dump(mode="json")
        if name == "matched-comparison-plan.v1":
            changed["plugin_scope"]["cases"][0]["baseline_scorer"]["candidate"]["content_sha256"] = "e" * 64
        elif name == "matched-pair-assessment.v1":
            changed["candidate_score"] = 0.1
        elif name == "matched-calibration.v1":
            changed["judgments"][0]["dimensions"][0]["score"] = 1.0
        elif name == "matched-execution.v1":
            changed["pairs"][0]["candidate_evaluation"]["case_results"][0]["observation_sha256"] = "e" * 64
        elif name == "matched-cloud-handoff.v1":
            changed["local_receipt_sha256"] = "e" * 64
        elif name == "matched-cloud-execution.v1":
            changed["handoff_sha256"] = "e" * 64
        elif name == "matched-regression.v1":
            changed["fixture_after"]["files"][0]["sha256"] = "e" * 64
        else:
            changed["handoff"]["local_receipt_sha256"] = "e" * 64
        validator.validate(changed)
        with pytest.raises(ValidationError):
            model.model_validate(changed)
        with pytest.raises(ContractError):
            registry.validate(name, changed)
        registry.validate(name, raw)


def test_cloud_recovery_requires_original_lineage_before_capability_access(tmp_path: Path) -> None:
    local, plan, calibrations, batch, events = _journey(tmp_path)
    handoff = evaluation.prepare_matched_cloud_handoff(local, plan)
    batch[0].candidate.provider.text = "behavior preserved; rm -rf"
    failed = asyncio.run(evaluation.execute_matched_cloud(handoff, calibrations, batch))
    batch[0].candidate.provider.text = "behavior preserved"
    events.clear()

    class Trap:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"premature cloud recovery access: {name}")

    guarded = tuple(replace(pair, candidate=replace(pair.candidate, provider=Trap(), judge=Trap())) for pair in batch)
    owners = ({"case_id": "case-0", "owner": "SDK maintainer"},)
    for initial, recovery_plan, assignments in (
        (local, plan, owners),
        (failed, local.plan, owners),
        (failed, plan, ()),
    ):
        blocked = asyncio.run(
            evaluation.execute_matched_cloud_regression(initial, assignments, recovery_plan, calibrations, guarded)
        )
        assert blocked.status == "blocked" and blocked.initial is None and not events
        SchemaRegistry().validate("matched-cloud-regression.v1", blocked.model_dump(mode="json"))
    recovered = asyncio.run(evaluation.execute_matched_cloud_regression(failed, owners, plan, calibrations, batch))
    assert recovered.status == "closed" and recovered.initial == failed and recovered.handoff.local == local
    assert events.count("provider") == events.count("dimensional_judge") == 40
    SchemaRegistry().validate("matched-cloud-regression.v1", recovered.model_dump(mode="json"))
