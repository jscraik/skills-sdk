"""Explicit callback budgets and descriptive, non-statistical matched summaries."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import ClassVar, Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_validator

from skills_sdk.models.matched_ingress import _MatchedContractModel


class MatchedRunBudget(_MatchedContractModel):
    """Limits for callback admission, not verified expenditure or hard cancellation."""

    maximum_provider_invocations: int = Field(strict=True, ge=1, le=128)
    maximum_judge_invocations: int = Field(strict=True, ge=1, le=128)
    maximum_elapsed_seconds: float = Field(strict=True, gt=0, allow_inf_nan=False)
    maximum_reported_cost: str | None = Field(default=None, max_length=128)
    currency: str | None = None

    @field_validator("maximum_reported_cost", mode="before")
    @classmethod
    def decimal_cost(cls, value: object) -> object:
        """Keep the requested amount exact without inventing a billing observation."""
        if value is not None and (
            type(value) is not str or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is None
        ):
            raise ValueError("reported-cost limit requires a canonical nonnegative decimal string")
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def currency_code(cls, value: object) -> object:
        """Reject padding and coercion before inherited string normalization."""
        if value is not None and (type(value) is not str or re.fullmatch(r"[A-Z]{3}", value) is None):
            raise ValueError("reported-cost currency requires three uppercase ASCII letters")
        return value

    @model_validator(mode="after")
    def cost_fields_agree(self) -> Self:
        """A requested reported-cost limit names exactly one currency."""
        if (self.maximum_reported_cost is None) != (self.currency is None):
            raise ValueError("reported-cost limit and currency must be supplied together")
        return self


class MatchedSelectionPolicy(_MatchedContractModel):
    """Explicit minimum coverage and descriptive stability policy, not significance."""

    minimum_trials_per_case: int = Field(strict=True, ge=2, le=64)
    minimum_qualifying_case_count: int = Field(strict=True, ge=1, le=10)
    maximum_trial_delta_range: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)


def _mean(values: tuple[float, ...]) -> float:
    """Compute an equal-weight decimal mean without binary threshold drift."""
    return float(sum((Decimal(str(value)) for value in values), Decimal(0)) / len(values))


class MatchedCaseSummary(_MatchedContractModel):
    """Retain paired deltas and confidence eligibility for one managed case."""

    case_id: str = Field(min_length=1, max_length=128)
    deltas: tuple[float, ...] = Field(min_length=1, max_length=64)
    qualifying_confidence: tuple[bool, ...] = Field(min_length=1, max_length=64)
    mean_delta: float = Field(strict=True, ge=-1, le=1, allow_inf_nan=False)
    delta_range: float = Field(strict=True, ge=0, le=2, allow_inf_nan=False)

    @field_validator("case_id", mode="before")
    @classmethod
    def exact_case_id(cls, value: object) -> object:
        """Keep the supplied case identifier exact and public."""
        if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value) is None:
            raise ValueError("matched case identifier requires an exact public token")
        return value

    @field_validator("deltas", "qualifying_confidence", mode="before")
    @classmethod
    def exact_observations(cls, value: object, info: ValidationInfo) -> object:
        """Reject coercion before nested sequence parsing can hide malformed evidence."""
        expected = float if info.field_name == "deltas" else bool
        if type(value) not in (tuple, list) or any(type(item) is not expected for item in value):
            raise ValueError("matched observations require exact numeric and boolean scalar types")
        return value

    @model_validator(mode="after")
    def observations_match(self) -> Self:
        """Recompute summaries from finite normalized paired observations."""
        if len(self.deltas) != len(self.qualifying_confidence):
            raise ValueError("every trial delta requires its confidence eligibility")
        if any(not -1 <= value <= 1 for value in self.deltas):
            raise ValueError("trial deltas must be finite normalized differences")
        spread = float(Decimal(str(max(self.deltas))) - Decimal(str(min(self.deltas))))
        if self.mean_delta != _mean(self.deltas) or self.delta_range != spread:
            raise ValueError("case summaries must equal their retained observations")
        return self


def _decision(
    cases: tuple[MatchedCaseSummary, ...], policy: MatchedSelectionPolicy, threshold: float, mean: float
) -> Literal["candidate", "baseline", "unchanged", "inconclusive"]:
    """Apply coverage, confidence and range rules before directional selection."""
    if any(
        len(case.deltas) < policy.minimum_trials_per_case
        or not all(case.qualifying_confidence)
        or case.delta_range > policy.maximum_trial_delta_range
        for case in cases
    ):
        return "inconclusive"
    if abs(mean) < threshold:
        return "unchanged"
    direction = 1 if mean > 0 else -1
    count = sum(direction * case.mean_delta >= threshold for case in cases)
    if count < policy.minimum_qualifying_case_count:
        return "inconclusive"
    return "candidate" if direction == 1 else "baseline"


class MatchedLaneSummary(_MatchedContractModel):
    """Recomputed ten-case outcome, without statistical or promotion authority."""

    policy: MatchedSelectionPolicy
    minimum_normalized_delta: float = Field(strict=True, gt=0, le=1, allow_inf_nan=False)
    cases: tuple[MatchedCaseSummary, ...] = Field(min_length=10, max_length=10)
    mean_delta: float = Field(strict=True, ge=-1, le=1, allow_inf_nan=False)
    decision: Literal["candidate", "baseline", "unchanged", "inconclusive"]

    _ingress_work_limit: ClassVar[int] = 16384

    @model_validator(mode="after")
    def summary_matches_cases(self) -> Self:
        """Ten unique ordered cases have equal weight and one derived decision."""
        if len({case.case_id for case in self.cases}) != 10:
            raise ValueError("matched summary requires ten unique managed case identifiers")
        expected_mean = _mean(tuple(case.mean_delta for case in self.cases))
        expected_decision = _decision(self.cases, self.policy, self.minimum_normalized_delta, expected_mean)
        if self.mean_delta != expected_mean or self.decision != expected_decision:
            raise ValueError("lane summary must equal its evidence and selection policy")
        return self


def build_matched_lane_summary(
    observations: tuple[tuple[str, tuple[float, ...], tuple[bool, ...]], ...],
    *,
    policy: MatchedSelectionPolicy,
    minimum_normalized_delta: float,
) -> MatchedLaneSummary:
    """Build a pure derived summary; repetitions do not create new managed cases."""
    active = MatchedSelectionPolicy.model_validate(policy)
    if type(minimum_normalized_delta) is not float or not 0 < minimum_normalized_delta <= 1:
        raise ValueError("matched threshold requires a finite positive normalized delta")
    if type(observations) is not tuple or len(observations) != 10:
        raise ValueError("matched summary requires exactly ten ordered case observations")
    cases: list[MatchedCaseSummary] = []
    for observation in observations:
        if type(observation) is not tuple or len(observation) != 3:
            raise ValueError("matched case observations require identifier, deltas and confidence")
        case_id, deltas, confidence = observation
        if (
            type(deltas) is not tuple
            or not 1 <= len(deltas) <= 64
            or any(type(value) is not float or not math.isfinite(value) or not -1 <= value <= 1 for value in deltas)
        ):
            raise ValueError("matched deltas require bounded exact numeric tuples")
        spread = float(Decimal(str(max(deltas))) - Decimal(str(min(deltas))))
        cases.append(
            MatchedCaseSummary(
                case_id=case_id,
                deltas=deltas,
                qualifying_confidence=confidence,
                mean_delta=_mean(deltas),
                delta_range=spread,
            )
        )
    values = tuple(cases)
    mean = _mean(tuple(case.mean_delta for case in values))
    return MatchedLaneSummary(
        policy=active,
        minimum_normalized_delta=minimum_normalized_delta,
        cases=values,
        mean_delta=mean,
        decision=_decision(values, active, minimum_normalized_delta, mean),
    )


__all__ = [
    "MatchedCaseSummary",
    "MatchedLaneSummary",
    "MatchedRunBudget",
    "MatchedSelectionPolicy",
    "build_matched_lane_summary",
]
