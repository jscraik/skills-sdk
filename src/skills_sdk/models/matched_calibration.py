"""Observed calibration with retained, rubric-bound dimensional judgments."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.matched_comparison import (
    MatchedComparisonRubric,
    MatchedVariantJudgment,
)
from skills_sdk.models.matched_ingress import _MatchedContractModel
from skills_sdk.models.observed_calibration import (
    CalibrationJudgeVerdict,
    ObservedCalibrationReceipt,
)
from skills_sdk.models.safety import PackageSafetyBlocker


def _dimension_score(rubric: MatchedComparisonRubric, judgment: MatchedVariantJudgment) -> float:
    if tuple(item.dimension_id for item in judgment.dimensions) != tuple(
        item.dimension_id for item in rubric.dimensions
    ):
        raise ValueError("calibration must cover every rubric dimension exactly once")
    if any(not set(row.evidence_refs).issubset(judgment.evidence.evidence_refs) for row in judgment.dimensions):
        raise ValueError("calibration dimensions must reference retained judge evidence")
    if any(reference.startswith("judge-results/") for row in judgment.dimensions for reference in row.evidence_refs):
        raise ValueError("calibration dimensions require underlying evidence, not the derived result reference")
    ranks = {"low": 0, "medium": 1, "high": 2}
    if ranks[judgment.confidence] < ranks[rubric.minimum_confidence]:
        raise ValueError("calibration judgment confidence is below the frozen rubric policy")
    return float(
        sum(
            Decimal(str(row.score)) * Decimal(str(dimension.weight))
            for row, dimension in zip(judgment.dimensions, rubric.dimensions, strict=True)
        )
        / Decimal(5)
    )


def _dimension_digest(rubric: MatchedComparisonRubric, judgment: MatchedVariantJudgment) -> str:
    payload = judgment.model_dump(mode="json", exclude={"evidence": {"judge_result_sha256"}})
    payload["evidence"]["evidence_refs"] = [
        reference for reference in payload["evidence"]["evidence_refs"] if not reference.startswith("judge-results/")
    ]
    return canonical_json_sha256({"rubric": rubric.model_dump(mode="json"), "judgment": payload})


class MatchedCalibrationReceipt(_MatchedContractModel):
    """Retain observed numeric calibration and the dimensional proof behind it."""

    schema_version: Literal["matched-calibration/v1"] = "matched-calibration/v1"
    rubric: MatchedComparisonRubric | None = None
    calibration: ObservedCalibrationReceipt | None = None
    judgments: tuple[MatchedVariantJudgment, ...] = Field(default=(), max_length=128)
    status: Literal["pass", "blocked"]
    blocker: PackageSafetyBlocker | None = None
    external_authenticity_verified: Literal[False] = False
    promotion_authorized: Literal[False] = False

    _ingress_work_limit: ClassVar[int] = 65536

    @field_validator("external_authenticity_verified", "promotion_authorized", mode="before")
    @classmethod
    def false_only(cls, value: object) -> object:
        if value is not False:
            raise ValueError("matched calibration cannot claim authenticity or authorise promotion")
        return value

    @model_validator(mode="after")
    def dimensions_bind_observed_results(self) -> MatchedCalibrationReceipt:
        if self.calibration is None or self.rubric is None:
            if self.calibration is not None or self.rubric is not None:
                raise ValueError("unbound matched calibration cannot retain partial execution evidence")
            if self.status != "blocked" or self.blocker is None or self.judgments:
                raise ValueError("unbound matched calibration requires an input blocker and no judgments")
            if self.blocker.code != "invalid_matched_calibration":
                raise ValueError("unbound matched calibration requires its input blocker")
            return self
        if len(self.judgments) != len(self.calibration.results):
            raise ValueError("matched calibration must retain each observed dimensional judgment")
        plan = self.calibration.plan
        for judgment, result in zip(self.judgments, self.calibration.results, strict=True):
            score = _dimension_score(self.rubric, judgment)
            evidence = judgment.evidence
            if evidence.judge_result_sha256 != _dimension_digest(self.rubric, judgment):
                raise ValueError("matched calibration must bind complete dimensional evidence")
            result_references = tuple(
                reference for reference in evidence.evidence_refs if reference.startswith("judge-results/")
            )
            if result_references != (f"judge-results/{evidence.judge_result_sha256}",):
                raise ValueError("matched calibration requires its bound dimensional result reference")
            if plan is None or evidence.candidate != plan.candidate or evidence.judge != plan.judge:
                raise ValueError("matched calibration judgments must bind candidate and judge")
            if (
                evidence.assertion_contract_sha256 != plan.assertion_contract_sha256
                or evidence.output_sha256 != result.output_sha256
            ):
                raise ValueError("matched calibration judgments must bind held-out criteria and outputs")
            numeric = CalibrationJudgeVerdict(evidence=evidence, score=score)
            if (
                score != result.score
                or canonical_json_sha256(numeric.model_dump(mode="json")) != result.judge_result_sha256
            ):
                raise ValueError("matched calibration scores must equal retained dimensional evidence")
        if self.status == "pass":
            if self.calibration.status != "pass" or self.blocker is not None:
                raise ValueError("passing matched calibration requires complete observed calibration")
        elif self.calibration.status != "blocked" or self.blocker != self.calibration.blocker:
            raise ValueError("blocked matched calibration must retain its observed blocker")
        return self
