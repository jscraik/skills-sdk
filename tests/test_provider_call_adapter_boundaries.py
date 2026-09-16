from __future__ import annotations

import asyncio
import traceback
from collections.abc import AsyncIterator, Awaitable
from typing import Literal, cast

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.models.provider_call import ProviderCostObservation
from skills_sdk.models.provider_execution import ProviderExecutionRequest, ProviderUsageMetadata
from skills_sdk.providers import (
    ProviderAdapterBatch,
    ProviderAdapterComplete,
    ProviderAdapterStreamItem,
    ProviderAdapterTerminal,
    ProviderCallLimits,
    execute_provider_call,
)
from tests.test_provider_call import FakeAdapter, FakeClock, _provider_request, _run


def test_selected_complete_mode_does_not_require_stream_member() -> None:
    request = _provider_request(None)
    base = FakeAdapter(request)

    class CompleteOnlyAdapter:
        descriptor = base.descriptor
        clock = base.clock

        async def complete(self, request: ProviderExecutionRequest, input_payload: object) -> ProviderAdapterComplete:
            return ProviderAdapterComplete("answer", ("evidence/output.json",))

        async def cleanup(self) -> None:
            base.cleanup_calls += 1

    assert _run(request, None, cast(object, CompleteOnlyAdapter())).complete_text == "answer"
    assert base.cleanup_calls == 1


def test_selected_stream_mode_does_not_require_complete_member() -> None:
    request = _provider_request(None)
    base = FakeAdapter(request, mode="stream")

    class StreamOnlyAdapter:
        descriptor = base.descriptor
        clock = base.clock

        async def _events(self) -> AsyncIterator[ProviderAdapterStreamItem]:
            yield ProviderAdapterTerminal(("evidence/output.json",))

        async def stream(
            self, request: ProviderExecutionRequest, input_payload: object
        ) -> AsyncIterator[ProviderAdapterStreamItem]:
            return self._events()

        async def cleanup(self) -> None:
            base.cleanup_calls += 1

    assert _run(request, None, cast(object, StreamOnlyAdapter())).public_result.status == "completed"
    assert base.cleanup_calls == 1


@pytest.mark.parametrize("member", ["now", "wait_for"])
def test_adapter_clock_members_are_not_used(member: str) -> None:
    request = _provider_request(None)

    class RaisingClock(FakeClock):
        def __getattribute__(self, name: str) -> object:
            if name == member:
                raise KeyError("PRIVATE_NESTED_CLOCK")
            return super().__getattribute__(name)

    adapter = FakeAdapter(request, clock=RaisingClock())
    assert asyncio.run(execute_provider_call(request, None, adapter, clock=FakeClock())).complete_text == "answer"


def test_adapter_clock_property_is_never_read() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request)
    reads = 0
    clock = adapter.clock

    class StatefulClockAdapter(FakeAdapter):
        @property
        def clock(self) -> FakeClock:
            nonlocal reads
            reads += 1
            if reads > 1:
                raise KeyError("PRIVATE_SECOND_CLOCK")
            return clock

        @clock.setter
        def clock(self, value: FakeClock) -> None:
            pass

    adapter = StatefulClockAdapter(request)
    outcome = asyncio.run(execute_provider_call(request, None, adapter, clock=clock))
    assert outcome.complete_text == "answer"
    assert reads == 0


def test_adapter_cannot_bypass_sdk_owned_deadline() -> None:
    request = _provider_request(None)

    class BypassClock(FakeClock):
        async def wait_for(self, awaitable: Awaitable[object], timeout_seconds: float) -> object:
            return await awaitable

    class StalledAdapter(FakeAdapter):
        async def complete(self, request: ProviderExecutionRequest, input_payload: object) -> ProviderAdapterComplete:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    adapter = StalledAdapter(request, clock=BypassClock())
    outcome = asyncio.run(
        execute_provider_call(request, None, adapter, limits=ProviderCallLimits(overall_seconds=0.01))
    )
    assert outcome.public_result.status == "failed"
    assert outcome.public_result.execution.error is not None
    assert outcome.public_result.execution.error.code == "provider_call_timeout"


def test_malformed_batch_container_is_a_contract_error() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request, mode="stream")
    adapter.stream_values = [ProviderAdapterBatch(cast(tuple, object()))]

    with pytest.raises(ContractError, match="invalid_provider_event"):
        _run(request, None, adapter)
    assert adapter.cleanup_calls == 1


@pytest.mark.parametrize("mode", ["complete", "stream"])
@pytest.mark.parametrize("field_name", ["usage", "cost"])
def test_unserializable_forged_adapter_evidence_is_redacted(
    mode: Literal["complete", "stream"], field_name: Literal["usage", "cost"]
) -> None:
    request = _provider_request(None)
    usage = ProviderUsageMetadata(unit_kind="tokens", input_units=1, output_units=1, total_units=2)
    cost = ProviderCostObservation(amount="0.25", currency="USD", observed_at="2026-09-08T10:00:00Z")
    if field_name == "usage":
        usage = usage.model_copy(update={"total_units": object()})
    else:
        cost = cost.model_copy(update={"amount": object()})
    adapter = FakeAdapter(request, mode=mode)
    terminal = ProviderAdapterComplete("answer", ("evidence/output.json",), usage=usage, cost=cost)
    if mode == "complete":
        adapter.complete_value = terminal
    else:
        adapter.stream_values = [ProviderAdapterTerminal(("evidence/output.json",), usage=usage, cost=cost)]
    with pytest.raises(ContractError, match="invalid_provider_event") as error:
        _run(request, None, adapter)
    formatted = "".join(traceback.format_exception(error.value))
    assert "object at 0x" not in formatted
    assert error.value.__cause__ is None
    assert adapter.cleanup_calls == 1
