from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Literal, TypeVar, cast

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.models.provider_call import ProviderCostObservation
from skills_sdk.providers import (
    ProviderAdapterChunk,
    ProviderAdapterComplete,
    ProviderAdapterTerminal,
    ProviderCallLimits,
    execute_provider_call,
)
from tests.test_provider_call import FakeAdapter, _provider_request, _run

_T = TypeVar("_T")


def test_limits_subclass_cannot_bypass_default_ceilings() -> None:
    class BypassLimits(ProviderCallLimits):
        def __post_init__(self) -> None:
            pass

    request = _provider_request(None)
    limits = BypassLimits(output_bytes=ProviderCallLimits().output_bytes + 1)
    with pytest.raises(ContractError, match="invalid_provider_limits"):
        _run(request, None, FakeAdapter(request), limits=limits)


@pytest.mark.parametrize("missing_member", ["now", "wait_for"])
def test_malformed_clock_protocol_is_rejected_before_adapter_execution(missing_member: str) -> None:
    request = _provider_request(None)

    class MalformedClock:
        def now(self) -> datetime:
            return datetime(2026, 9, 8, 10, 0, tzinfo=UTC)

        async def wait_for(self, awaitable: Awaitable[_T], timeout_seconds: float) -> _T:
            return await awaitable

        def __getattribute__(self, name: str) -> object:
            if name == missing_member:
                raise AttributeError("private missing clock member")
            return super().__getattribute__(name)

    adapter = FakeAdapter(request)
    with pytest.raises(ContractError, match="invalid_provider_clock") as error:
        asyncio.run(execute_provider_call(request, None, adapter, clock=cast(object, MalformedClock())))
    assert "private missing clock member" not in str(error.value)
    assert adapter.complete_calls == adapter.cleanup_calls == 0


@pytest.mark.parametrize("mode", ["complete", "stream"])
def test_unpaired_surrogate_adapter_text_is_an_invalid_event(mode: Literal["complete", "stream"]) -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request, mode=mode)
    if mode == "complete":
        adapter.complete_value = ProviderAdapterComplete("\ud800", ())
    else:
        adapter.stream_values = [ProviderAdapterChunk("\ud800"), ProviderAdapterTerminal(())]
    with pytest.raises(ContractError, match="invalid_provider_event"):
        _run(request, None, adapter)
    assert adapter.cleanup_calls == 1


@pytest.mark.parametrize("amount", ["1e3", "-0"])
def test_cost_amount_rejects_noncanonical_wire_forms(amount: str) -> None:
    with pytest.raises(ValueError, match="decimal string"):
        ProviderCostObservation(amount=amount, currency="USD", observed_at="2026-09-08T10:00:00Z")

    valid = ProviderCostObservation(amount="0", currency="USD", observed_at="2026-09-08T10:00:00Z")
    assert str(valid.amount) == "0"
