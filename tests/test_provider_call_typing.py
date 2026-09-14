from __future__ import annotations

from mypy import api as mypy_api


def _mypy(source: str) -> tuple[str, str, int]:
    return mypy_api.run(["--config-file", "/dev/null", "--command", source])


def test_provider_adapter_typing_accepts_exactly_one_selected_call_shape() -> None:
    shared = """
from collections.abc import AsyncIterator
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.providers import (
    JsonValue, ProviderAdapterComplete, ProviderAdapterStreamItem,
    ProviderCallClock, TextProviderAdapter,
)
class Base:
    descriptor: TextProviderAdapterDescriptor
    clock: ProviderCallClock
    async def cleanup(self) -> None: return None
def accepts(value: TextProviderAdapter) -> None: return None
"""
    complete = (
        shared
        + """
class Adapter(Base):
    async def complete(
        self, request: ProviderExecutionRequest, input_payload: JsonValue
    ) -> ProviderAdapterComplete:
        raise NotImplementedError
accepts(Adapter())
"""
    )
    stream = (
        shared
        + """
class Adapter(Base):
    def stream(
        self, request: ProviderExecutionRequest, input_payload: JsonValue
    ) -> AsyncIterator[ProviderAdapterStreamItem]:
        raise NotImplementedError
accepts(Adapter())
"""
    )
    missing = (
        shared
        + """
class Adapter(Base):
    pass
accepts(Adapter())
"""
    )

    for valid in (complete, stream):
        stdout, stderr, status = _mypy(valid)
        assert status == 0, stdout + stderr
    stdout, stderr, status = _mypy(missing)
    assert status != 0
    assert "incompatible type" in stdout.lower()
