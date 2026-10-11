"""Explicit profile inputs for the existing supplied-offline matched CLI."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.matched_admission import MatchedTrialAdapters
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.providers import JsonValue, ProviderAdapterComplete, ProviderAdapterStreamItem
from skills_sdk.providers.codex_profiles import (
    CodexProfiledCompleteAdapter,
    CodexProfiledJudgeAdapter,
    CodexProfiledStreamingAdapter,
    CodexProfileInvocation,
    CodexProfileSource,
    compile_codex_profile,
)


def _source(raw: object) -> tuple[CodexProfileSource, str]:
    from skills_sdk.cli.matched_offline import _object

    data = _object(
        raw, {"name", "profile_toml", "provider_toml", "catalogue_json", "defaults_toml", "configuration_sha256"}
    )
    digest = data["configuration_sha256"]
    if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("profile fixture requires its expected configuration digest")
    values = []
    for key in ("profile_toml", "provider_toml", "catalogue_json", "defaults_toml"):
        value = data[key]
        if value is None and key != "profile_toml":
            values.append(None)
        elif type(value) is str and len(value) <= 1_048_576:
            values.append(value.encode("utf-8"))
        else:
            raise ValueError("profile fixture inputs must be explicit bounded text or null")
    return CodexProfileSource(data["name"], *values), digest


@dataclass(frozen=True, slots=True)
class _ProfileFixtureDriver:
    delegate: object
    expected_sha256: str

    def _check(self, invocation: CodexProfileInvocation) -> None:
        if invocation.configuration_sha256 != self.expected_sha256:
            raise ContractError(
                "model_profile_fixture_mismatch", "fixture does not match the compiled profile configuration"
            )

    async def complete(
        self, invocation: CodexProfileInvocation, request: object, payload: JsonValue
    ) -> ProviderAdapterComplete:
        self._check(invocation)
        return await self.delegate.complete(request, payload)

    async def stream(
        self, invocation: CodexProfileInvocation, request: object, payload: JsonValue
    ) -> AsyncIterator[ProviderAdapterStreamItem]:
        self._check(invocation)
        return await self.delegate.stream(request, payload)

    async def judge(self, invocation: CodexProfileInvocation, inputs: object) -> object:
        self._check(invocation)
        return await self.delegate.judge(inputs)

    async def cleanup(self) -> None:
        return await self.delegate.cleanup()


@dataclass(frozen=True, slots=True)
class _ProfileSelection:
    plan: MatchedComparisonPlan
    generator: tuple[CodexProfileSource, str]
    judge: tuple[CodexProfileSource, str]

    def trial(self, trial: object) -> MatchedTrialAdapters:
        source, expected = self.generator
        factory = (
            CodexProfiledStreamingAdapter
            if trial.provider.descriptor.mode == "stream"
            else CodexProfiledCompleteAdapter
        )
        provider = factory(self.plan, source, _ProfileFixtureDriver(trial.provider, expected))
        source, expected = self.judge
        judge = CodexProfiledJudgeAdapter(self.plan, source, _ProfileFixtureDriver(trial.judge, expected))
        if (
            provider.descriptor != trial.provider.descriptor
            or provider.parameters != trial.provider.parameters
            or judge.identity != trial.judge.identity
            or judge.parameters != trial.judge.parameters
        ):
            raise ValueError("profile fixture identity or settings do not match the frozen lane")
        return MatchedTrialAdapters(provider, judge)

    def variant(self, item: object) -> object:
        first = self.trial(item)
        return replace(
            item,
            provider=first.provider,
            judge=first.judge,
            additional_trials=tuple(self.trial(trial) for trial in item.additional_trials),
        )


def _profile_selection(plan: object, raw: object) -> _ProfileSelection:
    from skills_sdk.cli.matched_offline import _object

    data = _object(raw, {"generator", "judge"})
    generator, judge = _source(data["generator"]), _source(data["judge"])
    if generator[0].name != judge[0].name:
        raise ValueError("generator and judge profiles must select the same lane")
    current = MatchedComparisonPlan.model_validate(plan)
    for role, (source, expected) in (("generator", generator), ("judge", judge)):
        if compile_codex_profile(current, source, role).configuration_sha256 != expected:
            raise ContractError(
                "model_profile_fixture_mismatch", "fixture must bind its compiled profile before callbacks"
            )
    return _ProfileSelection(current, generator, judge)


def _profile_batch(batch: tuple[object, ...], plan: object, raw: object) -> tuple[object, ...]:
    selection = _profile_selection(plan, raw)
    return tuple(
        replace(pair, baseline=selection.variant(pair.baseline), candidate=selection.variant(pair.candidate))
        for pair in batch
    )


def _profile_calibration(frames: tuple[object, ...], plan: object, raw: object) -> tuple[object, ...]:
    from skills_sdk.evaluation.observed_calibration import CalibrationTrialAdapters

    selection = _profile_selection(plan, raw)
    seen: set[int] = set()
    for frame in frames:
        for trial in (frame, *frame.trial_adapters):
            for adapter in (trial.provider, trial.judge):
                if id(adapter) in seen:
                    raise ValueError("profile calibration requires independently owned trial capabilities")
                seen.add(id(adapter))
    result = []
    for frame in frames:
        first = selection.trial(frame)
        later = tuple(selection.trial(trial) for trial in frame.trial_adapters)
        result.append(
            replace(
                frame,
                provider=first.provider,
                judge=first.judge,
                trial_adapters=tuple(CalibrationTrialAdapters(item.provider, item.judge) for item in later),
            )
        )
    return tuple(result)
