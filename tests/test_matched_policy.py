"""Pure matched selection and explicit callback-budget policy regressions."""

from __future__ import annotations

import pytest

from skills_sdk.models.matched_policy import (
    MatchedLaneSummary,
    MatchedRunBudget,
    MatchedSelectionPolicy,
    build_matched_lane_summary,
)


def _policy(**changes: object) -> MatchedSelectionPolicy:
    """Keep all synthetic selection settings explicit."""
    return MatchedSelectionPolicy.model_validate(
        {"minimum_trials_per_case": 2, "minimum_qualifying_case_count": 6, "maximum_trial_delta_range": 0.2, **changes}
    )


def _observations(delta: float = 0.2) -> tuple[tuple[str, tuple[float, ...], tuple[bool, ...]], ...]:
    """Repeat ten fixed synthetic cases, without expanding the managed set."""
    return tuple((f"case-{index}", (delta, delta), (True, True)) for index in range(10))


def _summary(delta: float = 0.2) -> MatchedLaneSummary:
    """Build a complete equally weighted deterministic fixture."""
    return build_matched_lane_summary(_observations(delta), policy=_policy(), minimum_normalized_delta=0.1)


@pytest.mark.parametrize(
    "delta,decision",
    [
        (0.2, "candidate"),
        (-0.2, "baseline"),
        (0.0, "unchanged"),
        (0.099, "unchanged"),
        (0.1, "candidate"),
        (-0.1, "baseline"),
    ],
)
def test_complete_summary_decisions_and_threshold_boundaries(delta: float, decision: str) -> None:
    result = _summary(delta)
    assert result.decision == decision and result.mean_delta == delta
    assert tuple(case.case_id for case in result.cases) == tuple(f"case-{index}" for index in range(10))
    assert MatchedLaneSummary.model_validate(result) == result


@pytest.mark.parametrize("kind", ["trials", "confidence", "unstable"])
def test_insufficient_or_unstable_case_is_inconclusive(kind: str) -> None:
    observations = list(_observations())
    if kind == "trials":
        observations[0] = ("case-0", (0.2,), (True,))
    elif kind == "confidence":
        observations[0] = ("case-0", (0.2, 0.2), (True, False))
    else:
        observations[0] = ("case-0", (-0.1, 0.5), (True, True))
    result = build_matched_lane_summary(tuple(observations), policy=_policy(), minimum_normalized_delta=0.1)
    assert result.decision == "inconclusive"
    assert _summary().decision == "candidate"


def test_range_boundary_and_equal_case_weight() -> None:
    observations = list(_observations())
    observations[0] = ("case-0", (0.1, 0.3), (True, True))
    observations[1] = ("case-1", (0.2,) * 4, (True,) * 4)
    result = build_matched_lane_summary(tuple(observations), policy=_policy(), minimum_normalized_delta=0.1)
    assert result.mean_delta == 0.2 and result.cases[0].delta_range == 0.2
    assert result.decision == "candidate"


@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
def test_boolean_collections_remain_distinct_from_scalar_flags(form: str) -> None:
    """Confidence collections retain strict members without becoming scalar flags."""
    good = _summary()
    raw = good.model_dump(mode="json")
    if form == "json":
        assert MatchedLaneSummary.model_validate_json(good.model_dump_json()) == good
    else:
        value = raw
        if form == "copy":
            value = good.model_copy(update=raw)
        elif form == "construct":
            value = MatchedLaneSummary.model_construct(**raw)
        assert MatchedLaneSummary.model_validate(value) == good
    raw["cases"][0]["qualifying_confidence"] = [1, 1]
    with pytest.raises(ValueError):
        MatchedLaneSummary.model_validate(raw)
    assert MatchedLaneSummary.model_validate(good) == good


def test_outlier_mean_without_qualifying_case_count_cannot_select() -> None:
    observations = tuple(
        (f"case-{index}", (0.5, 0.5) if index < 3 else (0.0, 0.0), (True, True)) for index in range(10)
    )
    result = build_matched_lane_summary(observations, policy=_policy(), minimum_normalized_delta=0.1)
    assert result.mean_delta == 0.15 and result.decision == "inconclusive"


@pytest.mark.parametrize("field,value", [("mean_delta", 0.5), ("decision", "baseline")])
@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
def test_forged_lane_summary_rejects_and_recovers(field: str, value: object, form: str) -> None:
    good = _summary()
    raw = {**good.model_dump(mode="json"), field: value}
    forged = (
        raw
        if form == "raw"
        else (good.model_copy(update={field: value}) if form == "copy" else MatchedLaneSummary.model_construct(**raw))
    )
    with pytest.raises(ValueError):
        MatchedLaneSummary.model_validate(forged)
    assert MatchedLaneSummary.model_validate(good) == good


@pytest.mark.parametrize(
    "field,value",
    [("mean_delta", 0.5), ("delta_range", 0.5), ("deltas", [True, True]), ("qualifying_confidence", [1, 1])],
)
def test_forged_nested_case_rejects(field: str, value: object) -> None:
    raw = _summary().model_dump(mode="json")
    raw["cases"][0][field] = value
    with pytest.raises(ValueError):
        MatchedLaneSummary.model_validate(raw)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 1.1, True, "0.2"])
def test_builder_rejects_bad_delta_values(value: object) -> None:
    observations = list(_observations())
    observations[0] = ("case-0", (value, value), (True, True))
    with pytest.raises(ValueError):
        build_matched_lane_summary(tuple(observations), policy=_policy(), minimum_normalized_delta=0.1)


@pytest.mark.parametrize("kind", ["empty", "nine", "eleven", "duplicate", "oversize", "mismatched", "padded"])
def test_observation_closure_and_work_bounds(kind: str) -> None:
    observations = list(_observations())
    if kind == "empty":
        observations[0] = ("case-0", (), ())
    elif kind == "nine":
        observations.pop()
    elif kind == "eleven":
        observations.append(("case-10", (0.2, 0.2), (True, True)))
    elif kind == "duplicate":
        observations[0] = observations[1]
    elif kind == "oversize":
        observations[0] = ("case-0", (0.2,) * 65, (True,) * 65)
    elif kind == "mismatched":
        observations[0] = ("case-0", (0.2, 0.2), (True,))
    else:
        observations[0] = (" case-0 ", (0.2, 0.2), (True, True))
    with pytest.raises(ValueError):
        build_matched_lane_summary(tuple(observations), policy=_policy(), minimum_normalized_delta=0.1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("minimum_trials_per_case", 1),
        ("minimum_trials_per_case", True),
        ("minimum_qualifying_case_count", 11),
        ("maximum_trial_delta_range", float("nan")),
    ],
)
def test_selection_policy_requires_bounded_explicit_values(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _policy(**{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("maximum_provider_invocations", 129),
        ("maximum_judge_invocations", True),
        ("maximum_elapsed_seconds", float("inf")),
        ("maximum_elapsed_seconds", 0.0),
        ("maximum_reported_cost", 1.0),
        ("maximum_reported_cost", "NaN"),
        ("maximum_reported_cost", " 1.00 "),
        ("currency", " usd "),
    ],
)
def test_budget_strict_types_and_cost_pairing(field: str, value: object) -> None:
    raw = {
        "maximum_provider_invocations": 40,
        "maximum_judge_invocations": 40,
        "maximum_elapsed_seconds": 10.0,
        field: value,
    }
    with pytest.raises(ValueError):
        MatchedRunBudget.model_validate(raw)


def test_budget_cost_is_explicit_request_not_spend_authority() -> None:
    raw = {"maximum_provider_invocations": 40, "maximum_judge_invocations": 40, "maximum_elapsed_seconds": 10.0}
    budget = MatchedRunBudget.model_validate(raw)
    assert budget.maximum_reported_cost is None
    requested = MatchedRunBudget.model_validate({**raw, "maximum_reported_cost": "0.00", "currency": "GBP"})
    assert requested.maximum_reported_cost == "0.00"
    assert "promotion_authorized" not in requested.model_dump()
    for missing in ("currency", "maximum_reported_cost"):
        invalid = requested.model_dump()
        invalid.pop(missing)
        with pytest.raises(ValueError):
            MatchedRunBudget.model_validate(invalid)
