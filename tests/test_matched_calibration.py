"""Actual dimensional callbacks, recomputation, tamper rejection and recovery."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_live_selected_case import _Provider
from test_matched_comparison import _plan
from test_observed_calibration import _batch
from test_selected_case_evaluation import _evidence

from skills_sdk.evaluation.matched_calibration import execute_matched_calibration
from skills_sdk.evaluation.observed_calibration import CalibrationTrialAdapters
from skills_sdk.models.matched_calibration import MatchedCalibrationReceipt
from skills_sdk.models.matched_comparison import MatchedVariantJudgment
from skills_sdk.models.observed_calibration import ObservedCalibrationPlan


class DimensionJudge:
    def __init__(self, numeric: object, score: float, events: list[str]) -> None:
        self.identity, self.parameters = numeric.identity, numeric.parameters
        self.definition, self.request = numeric.definition, numeric.request
        self.score, self.events = score, events

    async def judge(self, inputs: object) -> object:
        self.events.append("dimensional_judge")
        assert "expected_label" not in inputs.__dataclass_fields__
        assert "expected_label" not in str(inputs.selected.request.model_dump(mode="json"))
        evidence = _evidence(self.definition, self.request, inputs.selected.output_text)
        return MatchedVariantJudgment(
            evidence=evidence,
            confidence="medium",
            dimensions=tuple(
                {
                    "dimension_id": item.dimension_id,
                    "score": self.score,
                    "rationale": "Retained evidence supports this judgment.",
                    "evidence_refs": ["evidence/assertion-review.json"],
                }
                for item in inputs.rubric.dimensions
            ),
        )

    async def cleanup(self) -> None:
        self.events.append("dimensional_cleanup")


def _dimensions(root: Path, count: int = 6, trials: int = 1) -> tuple[object, tuple[object, ...], list[str]]:
    plan, batch, events = _batch(root)
    raw = plan.model_dump(mode="json")
    ids = [f"held-out-{index}" for index in range(count)]
    texts = [f"observed held-out output {index}" for index in range(count)]
    raw["parameters"]["trial_count"] = trials
    raw["scorer"]["calibration_probe_ids"] = ids
    raw["probes"] = [
        {
            "probe_id": identifier,
            "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "expected_label": "pass" if index % 2 == 0 else "fail",
        }
        for index, (identifier, text) in enumerate(zip(ids, texts, strict=True))
    ]
    frames = tuple(
        replace(
            batch[0],
            provider=_Provider(batch[0].request, events, text),
            judge=DimensionJudge(batch[0].judge, 4.5 if index % 2 == 0 else 0.5, events),
        )
        for index, text in enumerate(texts)
    )
    plan = ObservedCalibrationPlan.model_validate(raw)
    for frame in frames:
        frame.judge.parameters = plan.parameters
    frames = tuple(
        replace(
            frame,
            trial_adapters=tuple(
                CalibrationTrialAdapters(
                    _Provider(frame.request, events, frame.provider.text),
                    DimensionJudge(frame.judge, frame.judge.score, events),
                )
                for _ in range(trials - 1)
            ),
        )
        for frame in frames
    )
    return plan, frames, events


def test_six_dimensional_callbacks_retain_recomputable_scores(tmp_path: Path) -> None:
    plan, batch, events = _dimensions(tmp_path)
    result = asyncio.run(execute_matched_calibration(plan, _plan().rubric, batch))
    assert result.status == "pass" and len(result.judgments) == 6
    assert events.count("dimensional_judge") == 6
    assert [item.score for item in result.calibration.results] == [0.9, 0.1] * 3
    assert not result.promotion_authorized and not result.external_authenticity_verified
    assert MatchedCalibrationReceipt.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("invalid_result", [False, {"cleanup": "invalid"}])
def test_dimensional_cleanup_return_is_not_discarded_then_recovers(tmp_path: Path, invalid_result: object) -> None:
    plan, batch, events = _dimensions(tmp_path)
    original_cleanup = batch[0].judge.cleanup

    async def malformed_cleanup() -> object:
        await original_cleanup()
        return invalid_result

    batch[0].judge.cleanup = malformed_cleanup
    blocked = asyncio.run(execute_matched_calibration(plan, _plan().rubric, batch))
    assert blocked.status == "blocked" and not blocked.judgments
    assert events.count("provider") == events.count("dimensional_judge") == 1
    assert events.count("dimensional_cleanup") == 1
    batch[0].judge.cleanup = original_cleanup
    events.clear()
    assert asyncio.run(execute_matched_calibration(plan, _plan().rubric, batch)).status == "pass"


def test_maximum_declared_batch_retains_all_dimensions(tmp_path: Path) -> None:
    plan, batch, events = _dimensions(tmp_path, count=64, trials=2)
    raw = _plan().rubric.model_dump(mode="json")
    raw["dimensions"] = [
        {"dimension_id": f"dimension-{index}", "criterion": "Assess the retained evidence.", "weight": 0.0625}
        for index in range(16)
    ]
    result = asyncio.run(execute_matched_calibration(plan, raw, batch))
    assert result.status == "pass" and len(result.judgments) == 128
    assert all(len(item.dimensions) == 16 for item in result.judgments)
    assert events.count("dimensional_judge") == 128
    assert MatchedCalibrationReceipt.model_validate_json(result.model_dump_json()) == result


def test_larger_receipt_still_rejects_cycles_oversize_and_copied_extras(tmp_path: Path) -> None:
    plan, batch, _ = _dimensions(tmp_path)
    result = asyncio.run(execute_matched_calibration(plan, _plan().rubric, batch))
    cycle: list[object] = []
    cycle.append(cycle)
    for malformed in (cycle, list(range(65537))):
        with pytest.raises(ValidationError, match=r"nesting or work boundary|work boundary|cycle"):
            MatchedCalibrationReceipt.model_validate(result.model_copy(update={"judgments": malformed}))
    row = result.judgments[0]
    forged = row.model_copy(
        update={"dimensions": (row.dimensions[0].model_copy(update={"unknown": "discarded"}), *row.dimensions[1:])}
    )
    with pytest.raises(ValidationError, match="unknown fields"):
        MatchedCalibrationReceipt.model_validate(
            result.model_copy(update={"judgments": (forged, *result.judgments[1:])})
        )
    assert MatchedCalibrationReceipt.model_validate(result).status == "pass"


@pytest.mark.parametrize("change", ["score", "reason", "rubric", "criterion", "promotion", "missing"])
def test_retained_calibration_tampering_rejects(change: str, tmp_path: Path) -> None:
    plan, batch, _ = _dimensions(tmp_path)
    result = asyncio.run(execute_matched_calibration(plan, _plan().rubric, batch))
    raw = result.model_dump(mode="json")
    if change == "score":
        raw["judgments"][0]["dimensions"][0]["score"] = 1.0
    elif change == "reason":
        raw["judgments"][0]["dimensions"][0]["rationale"] = "Altered rationale."
    elif change == "rubric":
        raw["rubric"]["dimensions"][0]["dimension_id"] = "changed-dimension"
    elif change == "criterion":
        raw["rubric"]["dimensions"][0]["criterion"] = "Different scoring criterion."
    elif change == "promotion":
        raw["promotion_authorized"] = True
    else:
        raw["judgments"].pop()
    with pytest.raises(ValidationError):
        MatchedCalibrationReceipt.model_validate(raw)
    assert MatchedCalibrationReceipt.model_validate(result).status == "pass"


def test_incomplete_batch_has_zero_callbacks_then_recovers(tmp_path: Path) -> None:
    plan, batch, events = _dimensions(tmp_path)
    result = asyncio.run(execute_matched_calibration(plan, _plan().rubric, batch[:1]))
    assert result.status == "blocked" and not result.judgments and not events
    assert asyncio.run(execute_matched_calibration(plan, _plan().rubric, batch)).status == "pass"


def test_false_positive_is_observed_then_rejected_and_recovers(tmp_path: Path) -> None:
    plan, batch, events = _dimensions(tmp_path)
    batch[1].judge.score = 4.5
    result = asyncio.run(execute_matched_calibration(plan, _plan().rubric, batch))
    assert result.status == "blocked" and result.blocker.code == "calibration_policy_failed"
    assert events.count("dimensional_judge") == 6 and len(result.judgments) == 6
    batch[1].judge.score = 0.5
    assert asyncio.run(execute_matched_calibration(plan, _plan().rubric, batch)).status == "pass"
