"""Observe native dimensional callbacks and assess already supplied matched pairs."""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.live_selected_case import _judge_bindings
from skills_sdk.evaluation.matched_calibration import _DimensionalCalibrationJudge
from skills_sdk.evaluation.observed_calibration import (
    CalibrationProbeExecution,
    _CalibrationJudge,
    _preflight,
    execute_native_calibration,
)
from skills_sdk.models.matched_comparison import MatchedComparisonRubric, MatchedVariantJudgment, _matched_pair_values
from skills_sdk.models.native_matched import (
    NativeMatchedCalibrationReceipt,
    NativeMatchedComparisonPlan,
    NativeMatchedPairAssessment,
)
from skills_sdk.models.observed_calibration import NativeCalibrationPlan, NativeCalibrationReceipt
from skills_sdk.models.safety import PackageSafetyBlocker
from skills_sdk.providers.call import _read_adapter
from skills_sdk.providers.codex_judge import CodexCalibrationJudgeAdapter, CodexJudgeAdapter


async def _admit_native_dimensions(
    plan: NativeCalibrationPlan, executions: tuple[CalibrationProbeExecution, ...]
) -> None:
    """Admit every original source and capability before wrappers hide ownership."""
    if _preflight(plan, executions) is not None:
        raise ValueError("native dimensional calibration requires a safe complete batch")
    for probe, item in zip(plan.probes, executions, strict=True):
        await _read_adapter(item.provider, item.request)
        # Existing Codex scalar adapters are not dimensional capabilities.
        if isinstance(item.judge, (CodexJudgeAdapter, CodexCalibrationJudgeAdapter)):
            raise ValueError("native scalar adapters cannot supply dimensional judgments")
        if await _judge_bindings(item.judge) is None:
            raise ValueError("native dimensional callback is unavailable")
        if await _judge_bindings(_CalibrationJudge(item.judge, plan, probe, 0)) is None:
            raise ValueError("native dimensional judge identity or settings drifted")


async def execute_native_matched_calibration(
    plan: object, rubric: object, executions: tuple[CalibrationProbeExecution, ...]
) -> NativeMatchedCalibrationReceipt:
    """Retain native dimensional observations through existing guarded execution."""
    try:
        parsed = NativeCalibrationPlan.model_validate(plan)
        scoring = MatchedComparisonRubric.model_validate(rubric)
        if parsed.rubric_sha256 != canonical_json_sha256(scoring.model_dump(mode="json")):
            raise ValueError("native dimensional rubric differs from the frozen identity")
        await _admit_native_dimensions(parsed, executions)
        wrappers = tuple(_DimensionalCalibrationJudge(item.judge, scoring) for item in executions)
        batch = tuple(replace(item, judge=wrapper) for item, wrapper in zip(executions, wrappers, strict=True))
    except (AttributeError, TypeError, ValueError, ContractError):
        return NativeMatchedCalibrationReceipt(
            status="blocked",
            blocker=PackageSafetyBlocker(
                code="invalid_matched_calibration", message="Native calibration requires bound dimensional inputs."
            ),
        )
    observed = await execute_native_calibration(parsed, batch)
    invocation_count = sum(wrapper.invocations for wrapper in wrappers)
    observed = NativeCalibrationReceipt.model_validate(
        observed.model_copy(
            update={
                "judge_invocation_count": invocation_count,
                "judge_execution_performed": invocation_count > 0,
            }
        )
    )
    retained = tuple(judgment for wrapper in wrappers for judgment in wrapper.judgments)[: len(observed.results)]
    return NativeMatchedCalibrationReceipt(
        rubric=scoring, calibration=observed, judgments=retained, status=observed.status, blocker=observed.blocker
    )


def assess_native_matched_pair(
    plan: object,
    lane: Literal["local", "cloud"],
    calibrations: tuple[object, object],
    baseline: object,
    candidate: object,
) -> NativeMatchedPairAssessment:
    """Recompute supplied judgments only after both exact calibration joins."""
    parsed: NativeMatchedComparisonPlan | None = None
    selected_lane: Literal["local", "cloud"] | None = None
    try:
        if lane not in ("local", "cloud"):
            raise ValueError("native comparison requires a declared lane")
        selected_lane = lane
        parsed = NativeMatchedComparisonPlan.model_validate(plan)
        left = MatchedVariantJudgment.model_validate(baseline)
        right = MatchedVariantJudgment.model_validate(candidate)
        left_score, right_score, decision = _matched_pair_values(parsed, lane, left, right)
        return NativeMatchedPairAssessment(
            plan=parsed,
            lane=lane,
            calibrations=calibrations,
            status="assessed",
            baseline=left,
            candidate=right,
            baseline_score=left_score,
            candidate_score=right_score,
            normalized_delta=right_score - left_score,
            decision=decision,
            regression_required=right_score < left_score,
        )
    except (TypeError, ValueError):
        return NativeMatchedPairAssessment(
            plan=parsed,
            lane=selected_lane,
            status="blocked",
            blocker=PackageSafetyBlocker(
                code="invalid_matched_judgments", message="Native comparison requires complete bound evidence."
            ),
        )
