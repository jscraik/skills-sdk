"""Judge configuration remains separate from generation and detects drift."""

import asyncio
import json
from dataclasses import replace

import pytest
from test_codex_profile_binding import _profile_plan
from test_codex_profile_invocation import _CONFIGURED
from test_matched_comparison import _judgment

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.matched_calibration import _DimensionalCalibrationJudge
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.providers._codex_profile_adapter import _CodexProfiledJudgeAdapter


class _JudgeDriver:
    def __init__(self, verdict: object) -> None:
        self.verdict = verdict
        self.calls = []
        self.cleanups = 0
        self.mutate = None

    async def judge(self, invocation: object, inputs: object) -> object:
        self.calls.append(invocation)
        if self.mutate is not None:
            self.mutate()
        return self.verdict

    async def cleanup(self) -> None:
        self.cleanups += 1


def test_profile_judge_uses_judge_parameters_and_existing_dimensional_validation() -> None:
    data = _profile_plan(_CONFIGURED).model_dump(mode="json")
    data["lanes"][0]["judge_parameters"]["temperature"] = 0.25
    plan = MatchedComparisonPlan.model_validate(data)
    driver = _JudgeDriver(_judgment(plan, "baseline", 4.0))
    adapter = _CodexProfiledJudgeAdapter(plan, _CONFIGURED, driver)
    assert adapter.identity == plan.lanes[0].judge
    assert adapter.parameters.temperature == 0.25
    wrapper = _DimensionalCalibrationJudge(adapter, plan.rubric)
    verdict = asyncio.run(wrapper.judge(object()))
    assert verdict.score == 0.8 and len(wrapper.judgments) == 1
    invocation = driver.calls[0]
    assert invocation.binding.role == "judge"
    assert json.loads(invocation.configuration_json)["temperature"] == 0.25
    asyncio.run(wrapper.cleanup())
    assert driver.cleanups == 1
    with pytest.raises(ContractError, match="model_profile_role_mismatch"):
        _ = adapter.descriptor


@pytest.mark.parametrize("during", [False, True])
def test_judge_drift_blocks_before_callback_or_discards_returned_verdict(during: bool) -> None:
    plan = _profile_plan(_CONFIGURED)
    driver = _JudgeDriver(_judgment(plan, "baseline", 4.0))
    adapter = _CodexProfiledJudgeAdapter(plan, _CONFIGURED, driver)
    changed = replace(_CONFIGURED, defaults_bytes=b'model_reasoning_effort = "high"')
    if during:
        driver.mutate = lambda: setattr(adapter, "source", changed)
    else:
        adapter.source = changed
    with pytest.raises(ContractError, match="model_profile_binding_changed"):
        asyncio.run(adapter.judge(object()))
    assert len(driver.calls) == int(during)
    corrected = _CodexProfiledJudgeAdapter(_profile_plan(changed), changed, _JudgeDriver(driver.verdict))
    assert asyncio.run(corrected.judge(object())) == driver.verdict
