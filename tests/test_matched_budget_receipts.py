"""Fail-closed budget and derived selection evidence at public receipt ingress."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError
from test_matched_execution import _matched

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import execute_matched_lane
from skills_sdk.models import MatchedExecutionReceipt
from skills_sdk.models.matched_calibration import _dimension_digest


@pytest.fixture(scope="module")
def completed(tmp_path_factory: pytest.TempPathFactory) -> MatchedExecutionReceipt:
    """Observe a complete two-trial lane through controlled in-process callbacks."""
    plan, calibrations, batch, _ = _matched(tmp_path_factory.mktemp("budget-receipt"), trials=2)
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "completed"
    return result


def _rejected(raw: dict[str, object], good: MatchedExecutionReceipt, form: str) -> None:
    """Exercise every supported public ingress and corrected-input recovery."""
    if form == "json":
        with pytest.raises(ValidationError):
            MatchedExecutionReceipt.model_validate_json(json.dumps(raw))
    else:
        value = raw
        if form == "copy":
            value = good.model_copy(update=raw)
        elif form == "construct":
            value = MatchedExecutionReceipt.model_construct(**raw)
        with pytest.raises(ValidationError):
            MatchedExecutionReceipt.model_validate(value)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-execution.v1", raw)
    assert MatchedExecutionReceipt.model_validate(good) == good
    SchemaRegistry().validate("matched-execution.v1", good.model_dump(mode="json"))


@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
@pytest.mark.parametrize("extra_provider,extra_judge", [(1, 0), (2, 0), (2, 1)])
def test_completed_counts_cannot_exceed_represented_pairs(
    completed: MatchedExecutionReceipt, form: str, extra_provider: int, extra_judge: int
) -> None:
    """The declared coverage ceiling already rejects extra unpaired invocations."""
    raw = completed.model_dump(mode="json")
    raw["provider_invocation_count"] += extra_provider
    raw["judge_invocation_count"] += extra_judge
    _rejected(raw, completed, form)


def test_completed_observations_cannot_relabel_the_frozen_generator_mode(completed: MatchedExecutionReceipt) -> None:
    """Changing the mode invalidates the retained trial request commitments."""
    raw = completed.model_dump(mode="json")
    raw["plan"]["lanes"][0]["generator_mode"] = "stream"
    _rejected(raw, completed, "raw")


@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
@pytest.mark.parametrize("offset", [0.0, 1.0])
def test_completed_receipt_cannot_reach_elapsed_deadline(
    completed: MatchedExecutionReceipt, form: str, offset: float
) -> None:
    """A runtime-expired deadline cannot be relabelled as completed evidence."""
    raw = completed.model_dump(mode="json")
    deadline = raw["plan"]["lanes"][0]["budget"]["maximum_elapsed_seconds"]
    raw["elapsed_seconds"] = deadline + offset
    _rejected(raw, completed, form)


@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
@pytest.mark.parametrize(
    "code",
    [
        "matched_time_budget_exhausted",
        "matched_provider_budget_exhausted",
        "matched_judge_budget_exhausted",
        "matched_cost_budget_unavailable",
        "matched_run_budget_insufficient",
    ],
)
def test_fake_budget_blockers_reject_and_recover(completed: MatchedExecutionReceipt, form: str, code: str) -> None:
    """Retain no observations, but reject a blocker without its mechanical cause."""
    raw = completed.model_dump(mode="json")
    raw.update(
        status="blocked",
        pairs=[],
        provider_invocation_count=0,
        judge_invocation_count=0,
        elapsed_seconds=0.0,
        blocker={"code": code, "message": "Budget blocked."},
    )
    if code in {"matched_cost_budget_unavailable", "matched_run_budget_insufficient"}:
        raw["calibrations"] = []
    _rejected(raw, completed, form)


@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
def test_requested_cost_bound_cannot_admit_completed_callbacks(completed: MatchedExecutionReceipt, form: str) -> None:
    """Cost is unsupported: a completed observed lane cannot acquire a spend-cap claim."""
    raw = completed.model_dump(mode="json")
    raw["plan"]["lanes"][0]["budget"].update(maximum_reported_cost="1.00", currency="GBP")
    _rejected(raw, completed, form)


def test_cost_blocker_has_zero_callbacks_and_recovers(completed: MatchedExecutionReceipt) -> None:
    """The supported cost-budget receipt is explicitly pre-execution and inconclusive."""
    raw = completed.model_dump(mode="json")
    raw["plan"]["lanes"][0]["budget"].update(maximum_reported_cost="1.00", currency="GBP")
    raw.update(
        status="blocked",
        pairs=[],
        calibrations=[],
        provider_invocation_count=0,
        judge_invocation_count=0,
        elapsed_seconds=0.0,
        blocker={"code": "matched_cost_budget_unavailable", "message": "Cost evidence unavailable."},
    )
    blocked = MatchedExecutionReceipt.model_validate(raw)
    assert blocked.summary is None
    SchemaRegistry().validate("matched-execution.v1", raw)
    for field, value in (("provider_invocation_count", 1), ("judge_invocation_count", 1), ("elapsed_seconds", 0.1)):
        _rejected({**raw, field: value}, completed, "raw")
    assert MatchedExecutionReceipt.model_validate(completed).status == "completed"


def test_elapsed_blocker_boundary_retains_valid_prefix(completed: MatchedExecutionReceipt) -> None:
    """Exact deadline and later are valid exhaustion, while below deadline is forged."""
    raw = completed.model_dump(mode="json")
    deadline = raw["plan"]["lanes"][0]["budget"]["maximum_elapsed_seconds"]
    raw.update(
        status="blocked",
        pairs=raw["pairs"][:1],
        provider_invocation_count=2,
        judge_invocation_count=2,
        elapsed_seconds=deadline,
        blocker={"code": "matched_time_budget_exhausted", "message": "Deadline reached."},
    )
    for elapsed in (deadline, deadline + 1.0):
        neighbour = {**raw, "elapsed_seconds": elapsed}
        assert MatchedExecutionReceipt.model_validate(neighbour).summary is None
        SchemaRegistry().validate("matched-execution.v1", neighbour)
    _rejected({**raw, "elapsed_seconds": deadline - 1.0}, completed, "raw")


def test_selection_minimum_cannot_exceed_lane_trials(completed: MatchedExecutionReceipt) -> None:
    """A receipt cannot retrofit a selection minimum its frozen lane could never meet."""
    assert completed.summary.decision == "candidate"
    assert "summary" not in completed.model_dump(mode="json")
    raw = completed.model_dump(mode="json")
    raw["plan"]["selection_policy"]["minimum_trials_per_case"] = 3
    with pytest.raises(ValidationError, match="frozen selection policy"):
        MatchedExecutionReceipt.model_validate(raw)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-execution.v1", raw)
    _rejected(
        {**completed.model_dump(mode="json"), "summary": completed.summary.model_dump(mode="json")},
        completed,
        "raw",
    )
    assert MatchedExecutionReceipt.model_validate(completed).summary.decision == "candidate"


def test_selection_unstable_trials_are_inconclusive_and_recover(completed: MatchedExecutionReceipt) -> None:
    """Even positive mean lift cannot select when a case exceeds its range policy."""
    raw = completed.model_dump(mode="json")
    original = completed.pairs[0].candidate
    dimensions = tuple(
        row.model_copy(update={"score": baseline.score})
        for row, baseline in zip(original.dimensions, completed.pairs[0].baseline.dimensions, strict=True)
    )
    judgment = original.model_copy(update={"dimensions": dimensions})
    digest = _dimension_digest(completed.plan.rubric, judgment)
    changed = judgment.model_dump(mode="json")
    references = [ref for ref in original.evidence.evidence_refs if not ref.startswith("judge-results/")]
    changed["evidence"].update(judge_result_sha256=digest, evidence_refs=[*references, f"judge-results/{digest}"])
    raw["pairs"][0]["candidate"] = changed
    unstable = MatchedExecutionReceipt.model_validate(raw)
    assert unstable.summary.decision == "inconclusive"
    SchemaRegistry().validate("matched-execution.v1", raw)
    assert MatchedExecutionReceipt.model_validate(completed).summary.decision == "candidate"
