"""Exercise profile drift during streaming through the public provider call."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from test_codex_profile_binding import _profile_plan
from test_codex_profile_invocation import _CONFIGURED, _request_for

from skills_sdk.core.errors import ContractError
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.providers import (
    ProviderAdapterChunk,
    ProviderAdapterStreamItem,
    ProviderAdapterTerminal,
    execute_provider_call,
)
from skills_sdk.providers._codex_profile_adapter import _CodexProfiledStreamingAdapter


def _stream_plan(source: object = _CONFIGURED) -> MatchedComparisonPlan:
    data = _profile_plan(source).model_dump(mode="json")
    data["lanes"][0]["generator_mode"] = "stream"
    return MatchedComparisonPlan.model_validate(data)


class _StreamDriver:
    def __init__(self) -> None:
        self.opens = self.pulls = self.closes = self.cleanups = 0
        self.mutate = None
        self.invocation = None

    async def stream(
        self, invocation: object, request: object, payload: object
    ) -> AsyncIterator[ProviderAdapterStreamItem]:
        self.opens += 1
        self.invocation = invocation

        async def values() -> AsyncIterator[ProviderAdapterStreamItem]:
            try:
                self.pulls += 1
                yield ProviderAdapterChunk("controlled answer")
                if self.mutate is not None:
                    self.mutate()
                self.pulls += 1
                yield ProviderAdapterTerminal(("evidence/profile-stream.json",))
            finally:
                self.closes += 1

        return values()

    async def cleanup(self) -> None:
        self.cleanups += 1


def test_profile_stream_completes_with_single_cleanup_through_public_api() -> None:
    driver = _StreamDriver()
    adapter = _CodexProfiledStreamingAdapter(_stream_plan(), _CONFIGURED, driver)
    outcome = asyncio.run(execute_provider_call(_request_for(adapter), None, adapter))
    assert outcome.public_result.status == "completed"
    assert outcome.complete_text == "controlled answer"
    assert (driver.opens, driver.pulls, driver.closes, driver.cleanups) == (1, 2, 1, 1)
    assert driver.invocation.binding.profile_name == "oss-local.config.toml"


def test_profile_drift_mid_stream_discards_partial_output_and_closes_driver() -> None:
    driver = _StreamDriver()
    adapter = _CodexProfiledStreamingAdapter(_stream_plan(), _CONFIGURED, driver)
    changed = replace(_CONFIGURED, defaults_bytes=b'model_reasoning_effort = "high"')
    driver.mutate = lambda: setattr(adapter, "source", changed)
    with pytest.raises(ContractError, match="model_profile_binding_changed"):
        asyncio.run(execute_provider_call(_request_for(adapter), None, adapter))
    assert driver.cleanups == 1 and driver.closes == 1
    corrected = _CodexProfiledStreamingAdapter(_stream_plan(changed), changed, _StreamDriver())
    recovered = asyncio.run(execute_provider_call(_request_for(corrected), None, corrected))
    assert recovered.public_result.status == "completed"


def test_wrong_mode_blocks_before_stream_driver_access() -> None:
    driver = _StreamDriver()
    with pytest.raises(ContractError, match="model_profile_mode_unsupported"):
        _CodexProfiledStreamingAdapter(_profile_plan(_CONFIGURED), _CONFIGURED, driver)
    assert driver.opens == 0
