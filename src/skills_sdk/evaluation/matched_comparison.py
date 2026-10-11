"""Assess supplied dimensional judgments without pretending to execute models."""

from __future__ import annotations

from typing import Literal

from skills_sdk.models.matched_comparison import (
    MatchedComparisonPlan,
    MatchedPairAssessment,
    MatchedVariantJudgment,
    _matched_pair_values,
)
from skills_sdk.models.safety import PackageSafetyBlocker


def assess_matched_pair(
    plan: object,
    lane: Literal["local", "cloud"],
    baseline: object,
    candidate: object,
) -> MatchedPairAssessment:
    """Recompute matched lift; execution requires the separate guarded adapter route."""
    parsed: MatchedComparisonPlan | None = None
    selected_lane: Literal["local", "cloud"] | None = None
    try:
        if lane not in ("local", "cloud"):
            raise ValueError("matched comparison requires a declared lane")
        selected_lane = lane
        parsed = MatchedComparisonPlan.model_validate(plan)
        left = MatchedVariantJudgment.model_validate(baseline)
        right = MatchedVariantJudgment.model_validate(candidate)
        left_score, right_score, decision = _matched_pair_values(parsed, lane, left, right)
        return MatchedPairAssessment(
            plan=parsed,
            lane=selected_lane,
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
        return MatchedPairAssessment(
            plan=parsed,
            lane=selected_lane,
            status="blocked",
            blocker=PackageSafetyBlocker(
                code="invalid_matched_judgments",
                message="Matched comparison requires complete bound dimensional evidence.",
            ),
        )
