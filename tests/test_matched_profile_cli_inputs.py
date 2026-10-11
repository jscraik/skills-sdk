"""Explicit CLI profile selection wraps existing fixtures without host discovery."""

import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest
from test_codex_profile_binding import _profile_plan
from test_codex_profile_invocation import _CONFIGURED, _request_for
from test_matched_comparison import _judgment

from skills_sdk.cli.matched_offline import _FixtureJudge, _FixtureProvider
from skills_sdk.cli.matched_profiles import _profile_calibration, _profile_selection
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.matched_admission import MatchedTrialAdapters
from skills_sdk.evaluation.observed_calibration import CalibrationProbeExecution, CalibrationTrialAdapters
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.providers import execute_provider_call
from skills_sdk.providers.codex_profiles import CodexProfileSource, compile_codex_profile


def _profiles(plan: object, source: CodexProfileSource = _CONFIGURED) -> dict:
    raw = {
        "name": source.name,
        "profile_toml": source.profile_bytes.decode(),
        "provider_toml": source.provider_bytes.decode() if source.provider_bytes is not None else None,
        "catalogue_json": source.catalogue_bytes.decode() if source.catalogue_bytes is not None else None,
        "defaults_toml": source.defaults_bytes.decode() if source.defaults_bytes is not None else None,
    }
    return {
        role: dict(raw, configuration_sha256=compile_codex_profile(plan, source, role).configuration_sha256)
        for role in ("generator", "judge")
    }


def test_cli_profile_selection_applies_settings_to_fresh_fixture_adapters() -> None:
    plan = _profile_plan(_CONFIGURED)
    lane = plan.lanes[0]
    selection = _profile_selection(plan, _profiles(plan))
    original = MatchedTrialAdapters(
        _FixtureProvider(
            TextProviderAdapterDescriptor(provider=lane.generator, mode="complete"),
            lane.generator_parameters,
            "controlled answer",
            ("evidence/profile-fixture.json",),
        ),
        _FixtureJudge(lane.judge, lane.judge_parameters, _judgment(plan, "baseline", 4.0)),
    )
    first, second = selection.trial(original), selection.trial(original)
    assert first.provider is not second.provider and first.judge is not second.judge
    outcome = asyncio.run(execute_provider_call(_request_for(first.provider), None, first.provider))
    assert outcome.public_result.status == "completed" and outcome.complete_text == "controlled answer"
    assert asyncio.run(first.judge.judge(object())) == original.judge.judgment


@pytest.mark.parametrize("fault", ["digest", "lane", "unknown", "missing", "type"])
def test_invalid_profile_cli_inputs_reject_before_allocation_and_recover(fault: str) -> None:
    plan = _profile_plan(_CONFIGURED)
    valid = _profiles(plan)
    raw = deepcopy(valid)
    if fault == "digest":
        raw["judge"]["configuration_sha256"] = "0" * 64
    elif fault == "lane":
        raw["judge"]["name"] = "oss-cloud.config.toml"
    elif fault == "unknown":
        raw["generator"]["home"] = "/unavailable"
    elif fault == "missing":
        del raw["generator"]["profile_toml"]
    else:
        raw["generator"]["profile_toml"] = []
    with pytest.raises((ValueError, ContractError)):
        _profile_selection(plan, raw)
    assert _profile_selection(plan, valid).plan == plan


def test_calibration_profile_wrapping_preserves_fresh_trial_ownership() -> None:
    plan = _profile_plan(_CONFIGURED)
    lane = plan.lanes[0]
    provider = _FixtureProvider(
        TextProviderAdapterDescriptor(provider=lane.generator, mode="complete"),
        lane.generator_parameters,
        "controlled answer",
        ("evidence/profile-fixture.json",),
    )
    judge = _FixtureJudge(lane.judge, lane.judge_parameters, _judgment(plan, "baseline", 4.0))
    # This test exercises adapter composition only; the service validates probe inputs.
    frame = CalibrationProbeExecution(
        None,
        None,
        None,
        provider,
        judge,
        (CalibrationTrialAdapters(replace(provider), replace(judge)),),
    )
    wrapped = _profile_calibration((frame,), plan, _profiles(plan))[0]
    assert wrapped.provider is not wrapped.trial_adapters[0].provider
    assert wrapped.judge is not wrapped.trial_adapters[0].judge
    assert wrapped.provider.driver.delegate is provider
    assert wrapped.trial_adapters[0].provider.driver.delegate is frame.trial_adapters[0].provider
    aliased = replace(frame, trial_adapters=(CalibrationTrialAdapters(provider, judge),))
    with pytest.raises(ValueError, match="independently owned"):
        _profile_calibration((aliased,), plan, _profiles(plan))
    assert len(_profile_calibration((frame,), plan, _profiles(plan))) == 1
