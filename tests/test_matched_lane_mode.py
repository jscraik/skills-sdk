"""One frozen generation protocol across matched variants and repeated trials."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_matched_comparison import _plan
from test_matched_execution import _matched
from test_matched_trial_execution import StreamingProvider

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import execute_matched_lane
from skills_sdk.models import MatchedComparisonPlan


@pytest.mark.parametrize("position", ["baseline", "candidate", "trial", "later_case"])
def test_mixed_mode_blocks_without_a_completed_comparison_and_recovers(tmp_path: Path, position: str) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)
    index = -1 if position == "later_case" else 0
    role = "baseline" if position in {"baseline", "trial"} else "candidate"
    item = getattr(batch[index], role)
    if position == "trial":
        later = item.additional_trials[0]
        changed = replace(item, additional_trials=(replace(later, provider=StreamingProvider(later.provider)),))
    else:
        changed = replace(item, provider=StreamingProvider(item.provider))
    broken = list(batch)
    broken[index] = replace(batch[index], **{role: changed})
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, tuple(broken)))
    assert result.status == "blocked" and result.summary is None
    assert "stream_open" not in events
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


@pytest.mark.parametrize("mode", [None, True, "", "unsupported", " stream "])
@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
def test_plan_rejects_noncanonical_generator_mode(mode: object, form: str) -> None:
    good = _plan()
    raw = good.model_dump(mode="json")
    raw["lanes"][0]["generator_mode"] = mode
    value = raw
    if form == "copy":
        value = good.model_copy(update=raw)
    elif form == "construct":
        value = MatchedComparisonPlan.model_construct(**raw)
    with pytest.raises(ValueError):
        if form == "json":
            MatchedComparisonPlan.model_validate_json(json.dumps(raw))
        else:
            MatchedComparisonPlan.model_validate(value)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-comparison-plan.v1", raw)
    assert MatchedComparisonPlan.model_validate(good) == good


def test_mode_is_required_and_changes_plan_commitment() -> None:
    good = _plan()
    raw = good.model_dump(mode="json")
    del raw["lanes"][0]["generator_mode"]
    with pytest.raises(ValueError):
        MatchedComparisonPlan.model_validate(raw)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-comparison-plan.v1", raw)
    raw["lanes"][0]["generator_mode"] = "stream"
    streaming = MatchedComparisonPlan.model_validate(raw)
    assert streaming.digest != good.digest
    SchemaRegistry().validate("matched-comparison-plan.v1", raw)
