"""Canonical complete-output boundary regressions."""

from __future__ import annotations

import pytest
from test_provider_call import FakeAdapter, _provider_request, _run

from skills_sdk.core.errors import ContractError
from skills_sdk.providers import ProviderAdapterChunk, ProviderAdapterComplete


def test_complete_output_limit_uses_canonical_text_not_stateful_encode() -> None:
    class StatefulText(str):
        calls = 0

        def encode(self, *args: object, **kwargs: object) -> bytes:
            self.calls += 1
            if self.calls == 1:
                return b"x"
            return str.encode(self, *args, **kwargs)

    request = _provider_request(None)
    adapter = FakeAdapter(request)
    output = StatefulText("x" * 1_048_577)
    adapter.complete_value = ProviderAdapterComplete(output, ("evidence/output.json",))

    with pytest.raises(ContractError, match="provider_output_too_large"):
        _run(request, None, adapter)
    assert output.calls == 0


def test_stream_chunk_limit_uses_canonical_text_not_stateful_encode() -> None:
    class StatefulText(str):
        calls = 0

        def encode(self, *args: object, **kwargs: object) -> bytes:
            self.calls += 1
            return b"x"

    request = _provider_request(None)
    adapter = FakeAdapter(request, mode="stream")
    chunk = StatefulText("x" * 16_385)
    adapter.stream_values = [ProviderAdapterChunk(chunk)]

    with pytest.raises(ContractError, match="provider_chunk_too_large"):
        _run(request, None, adapter)
    assert chunk.calls == 0
