from __future__ import annotations

import asyncio
import hashlib
import json
import traceback
from collections.abc import AsyncIterator, Awaitable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeVar, cast

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.provider_call import (
    ProviderCallPublicResult,
    ProviderCostObservation,
    TextProviderAdapterDescriptor,
)
from skills_sdk.models.provider_execution import ProviderExecutionRequest, ProviderUsageMetadata
from skills_sdk.providers import (
    ProviderAdapterBatch,
    ProviderAdapterChunk,
    ProviderAdapterComplete,
    ProviderAdapterFailure,
    ProviderAdapterStreamItem,
    ProviderAdapterTerminal,
    ProviderCallLimits,
    ProviderCallOutcome,
    execute_provider_call,
)
from tests.test_provider_execution_contracts import _request

_T = TypeVar("_T")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _provider_request(
    input_payload: object = None, *, capability: str = "response_generation"
) -> ProviderExecutionRequest:
    payload = _request()
    payload["declared_capability"] = capability
    payload["input_sha256"] = hashlib.sha256(_canonical_bytes(input_payload)).hexdigest()
    return ProviderExecutionRequest.model_validate(payload)


class FakeClock:
    def __init__(self, *timeouts_to_fail: float) -> None:
        self.current = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
        self.timeouts_to_fail = list(timeouts_to_fail)
        self.observed_timeouts: list[float] = []

    def now(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value

    async def wait_for(self, awaitable: Awaitable[_T], timeout_seconds: float) -> _T:
        self.observed_timeouts.append(timeout_seconds)
        if timeout_seconds in self.timeouts_to_fail:
            self.timeouts_to_fail.remove(timeout_seconds)
            if isinstance(awaitable, Coroutine):
                awaitable.close()
            raise TimeoutError
        return await awaitable


class FakeAdapter:
    def __init__(
        self,
        request: ProviderExecutionRequest,
        *,
        mode: Literal["complete", "stream"] = "complete",
        clock: FakeClock | None = None,
    ) -> None:
        self.descriptor = TextProviderAdapterDescriptor.model_validate(
            {
                "provider": request.provider.model_dump(mode="json"),
                "mode": mode,
            }
        )
        self.clock = clock or FakeClock()
        self.complete_value: object = ProviderAdapterComplete("answer", ("evidence/provider-output.json",))
        self.stream_values: list[object] = [
            ProviderAdapterChunk("an"),
            ProviderAdapterChunk("swer"),
            ProviderAdapterTerminal(("evidence/provider-stream.json",)),
        ]
        self.cleanup_calls = 0
        self.cleanup_error: BaseException | None = None
        self.complete_calls = 0
        self.stream_pulls = 0
        self.inflight_pulls = 0
        self.maximum_inflight_pulls = 0

    async def complete(self, request: ProviderExecutionRequest, input_payload: object) -> ProviderAdapterComplete:
        self.complete_calls += 1
        if isinstance(self.complete_value, BaseException):
            raise self.complete_value
        return cast(ProviderAdapterComplete, self.complete_value)

    async def _stream(self) -> AsyncIterator[ProviderAdapterStreamItem]:
        for value in self.stream_values:
            self.stream_pulls += 1
            self.inflight_pulls += 1
            self.maximum_inflight_pulls = max(self.maximum_inflight_pulls, self.inflight_pulls)
            self.inflight_pulls -= 1
            if isinstance(value, BaseException):
                raise value
            yield cast(ProviderAdapterStreamItem, value)

    async def stream(
        self,
        request: ProviderExecutionRequest,
        input_payload: object,
    ) -> AsyncIterator[ProviderAdapterStreamItem]:
        return self._stream()

    async def cleanup(self) -> None:
        self.cleanup_calls += 1
        if self.cleanup_error is not None:
            raise self.cleanup_error


def _run(
    request: ProviderExecutionRequest,
    payload: object,
    adapter: FakeAdapter,
    **kwargs: object,
) -> ProviderCallOutcome:
    kwargs.setdefault("clock", adapter.clock)
    return asyncio.run(execute_provider_call(request, payload, adapter, **kwargs))


def test_complete_call_returns_private_output_and_public_bound_evidence() -> None:
    payload = {"prompt": "hello", "metadata": {"case": 1}}
    request = _provider_request(payload)
    adapter = FakeAdapter(request)

    outcome = _run(request, payload, adapter)

    assert outcome.complete_text == "answer"
    assert outcome.public_result.status == "completed"
    assert outcome.public_result.execution.validate_against_request(request)
    assert outcome.public_result.output_bytes == 6
    assert outcome.public_result.event_count == 1
    assert outcome.public_result.retry_attempts == 0
    assert outcome.public_result.cleanup_succeeded is True
    assert adapter.complete_calls == adapter.cleanup_calls == 1
    public_json = outcome.public_result.model_dump_json()
    assert "answer" not in public_json
    assert "hello" not in public_json


def test_non_ascii_input_uses_the_repository_canonical_digest() -> None:
    payload = {"prompt": "héllo"}
    request_payload = _request()
    request_payload["input_sha256"] = canonical_json_sha256(payload)
    request = ProviderExecutionRequest.model_validate(request_payload)

    assert _run(request, payload, FakeAdapter(request)).public_result.status == "completed"


def test_stream_call_is_pull_driven_and_has_one_terminal_result() -> None:
    payload = {"prompt": "hello"}
    request = _provider_request(payload)
    adapter = FakeAdapter(request, mode="stream")

    outcome = _run(request, payload, adapter)

    assert outcome.complete_text == "answer"
    assert outcome.public_result.event_count == 3
    assert outcome.public_result.max_inflight_pulls == 1
    assert outcome.public_result.max_buffered_events == 0
    assert adapter.maximum_inflight_pulls == 1
    assert adapter.stream_pulls == 3


def test_buffered_event_boundary_accepts_eight_and_rejects_nine() -> None:
    request = _provider_request(None)
    accepted = FakeAdapter(request, mode="stream")
    accepted.stream_values = [
        ProviderAdapterBatch(
            (*[ProviderAdapterChunk("x") for _ in range(7)], ProviderAdapterTerminal(("evidence/output.json",)))
        )
    ]
    outcome = _run(request, None, accepted)
    assert outcome.public_result.max_buffered_events == 8
    assert outcome.public_result.event_count == 8
    assert accepted.stream_pulls == 1

    rejected = FakeAdapter(request, mode="stream")
    rejected.stream_values = [ProviderAdapterBatch(tuple(ProviderAdapterChunk("x") for _ in range(9)))]
    with pytest.raises(ContractError, match="provider_buffer_limit_exceeded"):
        _run(request, None, rejected)


def test_zero_buffer_limit_accepts_direct_events_and_rejects_batches() -> None:
    request = _provider_request(None)
    direct = FakeAdapter(request, mode="stream")
    limits = ProviderCallLimits(buffered_events=0)
    assert _run(request, None, direct, limits=limits).public_result.max_buffered_events == 0

    batched = FakeAdapter(request, mode="stream")
    batched.stream_values = [ProviderAdapterBatch((ProviderAdapterTerminal(("evidence/output.json",)),))]
    with pytest.raises(ContractError, match="provider_buffer_limit_exceeded"):
        _run(request, None, batched, limits=limits)


def test_event_after_terminal_inside_buffer_is_rejected() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request, mode="stream")
    adapter.stream_values = [
        ProviderAdapterBatch((ProviderAdapterTerminal(("evidence/output.json",)), ProviderAdapterChunk("late")))
    ]
    with pytest.raises(ContractError, match="provider_event_after_terminal"):
        _run(request, None, adapter)


def test_unsupported_capability_is_blocked_without_adapter_execution() -> None:
    payload = None
    request = _provider_request(payload, capability="embedding")
    adapter = FakeAdapter(request)

    outcome = _run(request, payload, adapter)

    assert outcome.public_result.status == "blocked"
    assert outcome.public_result.execution.blocker is not None
    assert outcome.public_result.execution.blocker.code == "unsupported_provider_capability"
    assert adapter.complete_calls == adapter.stream_pulls == 0
    assert adapter.cleanup_calls == 1


@pytest.mark.parametrize(
    ("payload", "limits", "code"),
    [
        ({"prompt": "xx"}, ProviderCallLimits(input_bytes=10), "provider_input_too_large"),
        ({"metadata": "xx"}, ProviderCallLimits(metadata_bytes=3), "provider_metadata_too_large"),
        ([[[0]]], ProviderCallLimits(nesting_depth=2), "provider_input_depth_exceeded"),
        (("not", "json"), ProviderCallLimits(), "invalid_provider_input"),
    ],
)
def test_input_boundaries_fail_closed(payload: object, limits: ProviderCallLimits, code: str) -> None:
    request = _provider_request(payload)
    adapter = FakeAdapter(request)
    with pytest.raises(ContractError, match=code):
        _run(request, payload, adapter, limits=limits)
    assert adapter.complete_calls == 0


@pytest.mark.parametrize("field_name", ["overall_seconds", "idle_seconds", "cleanup_seconds"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0, 30.0001])
def test_timeout_limits_require_finite_positive_tightening(field_name: str, value: float) -> None:
    with pytest.raises(ValueError, match=field_name):
        ProviderCallLimits(**{field_name: value})


def test_timeout_limits_accept_defaults_and_exact_tightening_and_revalidate_forgery() -> None:
    request = _provider_request(None)
    assert _run(request, None, FakeAdapter(request), limits=ProviderCallLimits()).public_result.status == "completed"
    tightened = ProviderCallLimits(overall_seconds=0.5, idle_seconds=0.25, cleanup_seconds=0.125)
    assert _run(request, None, FakeAdapter(request), limits=tightened).public_result.status == "completed"

    forged = ProviderCallLimits()
    object.__setattr__(forged, "overall_seconds", float("nan"))
    with pytest.raises(ContractError, match="invalid_provider_limits"):
        _run(request, None, FakeAdapter(request), limits=forged)


def test_input_digest_and_adapter_identity_must_match() -> None:
    payload = {"prompt": "hello"}
    request = _provider_request(payload)
    adapter = FakeAdapter(request)
    forged_provider = adapter.descriptor.provider.model_copy(update={"adapter_id": "different-adapter"})
    adapter.descriptor = adapter.descriptor.model_copy(update={"provider": forged_provider})

    with pytest.raises(ContractError, match="provider_adapter_mismatch"):
        _run(request, payload, adapter)
    with pytest.raises(ContractError, match="provider_input_digest_mismatch"):
        _run(request, {"prompt": "changed"}, FakeAdapter(request))


def test_input_metadata_and_depth_accept_exact_limits() -> None:
    payload = {"metadata": "abcd"}
    payload_bytes = len(_canonical_bytes(payload))
    metadata_bytes = len(_canonical_bytes(payload["metadata"]))
    request = _provider_request(payload)
    limits = ProviderCallLimits(input_bytes=payload_bytes, metadata_bytes=metadata_bytes, nesting_depth=1)

    assert _run(request, payload, FakeAdapter(request), limits=limits).public_result.status == "completed"

    deeper = {"metadata": [0]}
    deep_request = _provider_request(deeper)
    with pytest.raises(ContractError, match="provider_input_depth_exceeded"):
        _run(deep_request, deeper, FakeAdapter(deep_request), limits=limits)


def test_default_input_metadata_and_depth_limits_are_exact() -> None:
    input_at_limit = "x" * (262_144 - 2)
    request = _provider_request(input_at_limit)
    assert _run(request, input_at_limit, FakeAdapter(request)).public_result.status == "completed"

    input_over_limit = input_at_limit + "x"
    over_request = _provider_request(input_over_limit)
    with pytest.raises(ContractError, match="provider_input_too_large"):
        _run(over_request, input_over_limit, FakeAdapter(over_request))

    metadata_at_limit = {"metadata": "x" * (65_536 - 2)}
    metadata_request = _provider_request(metadata_at_limit)
    assert _run(metadata_request, metadata_at_limit, FakeAdapter(metadata_request)).public_result.status == "completed"

    metadata_over_limit = {"metadata": "x" * (65_536 - 1)}
    over_metadata_request = _provider_request(metadata_over_limit)
    with pytest.raises(ContractError, match="provider_metadata_too_large"):
        _run(over_metadata_request, metadata_over_limit, FakeAdapter(over_metadata_request))

    nested: object = 0
    for _ in range(32):
        nested = [nested]
    nested_request = _provider_request(nested)
    assert _run(nested_request, nested, FakeAdapter(nested_request)).public_result.status == "completed"
    too_deep = [nested]
    deep_request = _provider_request(too_deep)
    with pytest.raises(ContractError, match="provider_input_depth_exceeded"):
        _run(deep_request, too_deep, FakeAdapter(deep_request))


@pytest.mark.parametrize(("mode", "limit_name"), [("complete", "output_bytes"), ("stream", "chunk_bytes")])
def test_output_and_chunk_limits_accept_boundary_and_reject_one_beyond(mode: str, limit_name: str) -> None:
    payload = None
    request = _provider_request(payload)
    accepted = FakeAdapter(request, mode=mode)
    rejected = FakeAdapter(request, mode=mode)
    if mode == "complete":
        accepted.complete_value = ProviderAdapterComplete("x" * 4, ("evidence/output.json",))
        rejected.complete_value = ProviderAdapterComplete("x" * 5, ("evidence/output.json",))
    else:
        accepted.stream_values = [ProviderAdapterChunk("x" * 4), ProviderAdapterTerminal(("evidence/output.json",))]
        rejected.stream_values = [ProviderAdapterChunk("x" * 5), ProviderAdapterTerminal(("evidence/output.json",))]
    limits = ProviderCallLimits(**{limit_name: 4})

    assert _run(request, payload, accepted, limits=limits).public_result.status == "completed"
    with pytest.raises(ContractError):
        _run(request, payload, rejected, limits=limits)


def test_default_complete_and_chunk_limits_are_exact() -> None:
    request = _provider_request(None)
    complete = FakeAdapter(request)
    complete.complete_value = ProviderAdapterComplete("x" * 1_048_576, ("evidence/output.json",))
    assert _run(request, None, complete).public_result.output_bytes == 1_048_576
    complete_over = FakeAdapter(request)
    complete_over.complete_value = ProviderAdapterComplete("x" * 1_048_577, ("evidence/output.json",))
    with pytest.raises(ContractError, match="provider_output_too_large"):
        _run(request, None, complete_over)

    stream = FakeAdapter(request, mode="stream")
    stream.stream_values = [ProviderAdapterChunk("x" * 16_384), ProviderAdapterTerminal(("evidence/output.json",))]
    assert _run(request, None, stream).public_result.output_bytes == 16_384
    stream_over = FakeAdapter(request, mode="stream")
    stream_over.stream_values = [ProviderAdapterChunk("x" * 16_385)]
    with pytest.raises(ContractError, match="provider_chunk_too_large"):
        _run(request, None, stream_over)


def test_event_limit_accepts_terminal_at_boundary_and_rejects_one_beyond() -> None:
    request = _provider_request(None)
    accepted = FakeAdapter(request, mode="stream")
    accepted.stream_values = [ProviderAdapterChunk("x"), ProviderAdapterTerminal(("evidence/output.json",))]
    rejected = FakeAdapter(request, mode="stream")
    rejected.stream_values = [ProviderAdapterChunk("x"), ProviderAdapterChunk("y")]
    limits = ProviderCallLimits(events=2)

    assert _run(request, None, accepted, limits=limits).public_result.event_count == 2
    with pytest.raises(ContractError, match="provider_event_limit_exceeded"):
        _run(request, None, rejected, limits=limits)


def test_default_event_limit_is_exact() -> None:
    request = _provider_request(None)
    accepted = FakeAdapter(request, mode="stream")
    accepted.stream_values = [
        *[ProviderAdapterChunk("x") for _ in range(4_095)],
        ProviderAdapterTerminal(("evidence/output.json",)),
    ]
    assert _run(request, None, accepted).public_result.event_count == 4_096

    rejected = FakeAdapter(request, mode="stream")
    rejected.stream_values = [ProviderAdapterChunk("x") for _ in range(4_096)]
    with pytest.raises(ContractError, match="provider_event_limit_exceeded"):
        _run(request, None, rejected)


def test_stream_total_output_accepts_boundary_and_rejects_one_beyond() -> None:
    request = _provider_request(None)
    accepted = FakeAdapter(request, mode="stream")
    accepted.stream_values = [
        ProviderAdapterChunk("ab"),
        ProviderAdapterChunk("cd"),
        ProviderAdapterTerminal(("evidence/output.json",)),
    ]
    rejected = FakeAdapter(request, mode="stream")
    rejected.stream_values = [ProviderAdapterChunk("ab"), ProviderAdapterChunk("cde")]
    limits = ProviderCallLimits(output_bytes=4)

    assert _run(request, None, accepted, limits=limits).public_result.output_bytes == 4
    with pytest.raises(ContractError, match="provider_output_too_large"):
        _run(request, None, rejected, limits=limits)


def test_stream_missing_terminal_fails_and_events_after_terminal_are_not_pulled() -> None:
    request = _provider_request(None)
    missing = FakeAdapter(request, mode="stream")
    missing.stream_values = [ProviderAdapterChunk("x")]
    with pytest.raises(ContractError, match="provider_stream_missing_terminal"):
        _run(request, None, missing)

    extra = FakeAdapter(request, mode="stream")
    extra.stream_values = [
        ProviderAdapterChunk("x"),
        ProviderAdapterTerminal(("evidence/output.json",)),
        ProviderAdapterChunk("ignored"),
    ]
    outcome = _run(request, None, extra)
    assert outcome.complete_text == "x"
    assert extra.stream_pulls == 2


@pytest.mark.parametrize("status", ["failed", "blocked", "indeterminate"])
def test_expected_failures_become_redacted_terminal_outcomes(
    status: Literal["failed", "blocked", "indeterminate"],
) -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request)
    adapter.complete_value = ProviderAdapterFailure(
        code="synthetic_failure",
        category="policy" if status == "blocked" else "provider",
        retryable=False,
        evidence_refs=("evidence/failure.json",),
        status=status,
    )

    outcome = _run(request, None, adapter)

    assert outcome.complete_text is None
    assert outcome.public_result.status == status
    assert "synthetic_failure" in outcome.public_result.model_dump_json()


@pytest.mark.parametrize("failure", [RuntimeError("private provider response"), KeyError("private mapping value")])
def test_unknown_exception_is_indeterminate_without_exception_text(failure: Exception) -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request)
    adapter.complete_value = failure

    outcome = _run(request, None, adapter)

    public_json = outcome.public_result.model_dump_json()
    assert outcome.public_result.status == "indeterminate"
    assert str(failure) not in public_json


@pytest.mark.parametrize(("timeout", "code"), [(30.0, "provider_call_timeout"), (5.0, "provider_idle_timeout")])
def test_overall_and_idle_timeout_are_typed(timeout: float, code: str) -> None:
    request = _provider_request(None)
    mode = "complete" if timeout == 30.0 else "stream"
    adapter = FakeAdapter(request, mode=mode, clock=FakeClock(timeout))

    outcome = _run(request, None, adapter)

    assert outcome.public_result.status == "failed"
    assert outcome.public_result.execution.error is not None
    assert outcome.public_result.execution.error.code == code
    assert adapter.cleanup_calls == 1


def test_idle_deadline_applies_after_a_stream_chunk() -> None:
    class EndOfStreamClock(FakeClock):
        async def wait_for(self, awaitable: Awaitable[_T], timeout_seconds: float) -> _T:
            if timeout_seconds == 5.0 and self.observed_timeouts.count(5.0) == 1:
                if isinstance(awaitable, Coroutine):
                    awaitable.close()
                raise TimeoutError
            return await super().wait_for(awaitable, timeout_seconds)

    request = _provider_request(None)
    adapter = FakeAdapter(request, mode="stream", clock=EndOfStreamClock())
    outcome = _run(request, None, adapter)
    assert outcome.public_result.execution.error is not None
    assert outcome.public_result.execution.error.code == "provider_idle_timeout"
    assert adapter.stream_pulls == 1


def test_cleanup_failure_preserves_primary_success_with_diagnostic() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request)
    adapter.cleanup_error = RuntimeError("private cleanup detail")

    outcome = _run(request, None, adapter)

    assert outcome.public_result.status == "completed"
    assert outcome.public_result.cleanup_succeeded is False
    assert outcome.public_result.cleanup_error_code == "cleanup_failed"
    assert "private cleanup detail" not in outcome.public_result.model_dump_json()


def test_cleanup_timeout_is_bounded_and_preserves_primary_success() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request, clock=FakeClock(1.0))

    outcome = _run(request, None, adapter)

    assert outcome.public_result.status == "completed"
    assert outcome.public_result.cleanup_error_code == "cleanup_failed"
    assert 1.0 in adapter.clock.observed_timeouts


def test_cleanup_failure_preserves_primary_failure() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request)
    adapter.complete_value = ProviderAdapterFailure(
        code="provider_failed",
        category="provider",
        retryable=False,
        evidence_refs=("evidence/failure.json",),
    )
    adapter.cleanup_error = RuntimeError("private cleanup detail")

    outcome = _run(request, None, adapter)

    assert outcome.public_result.status == "failed"
    assert outcome.public_result.execution.error is not None
    assert outcome.public_result.execution.error.code == "provider_failed"
    assert outcome.public_result.cleanup_error_code == "cleanup_failed"


def test_cancellation_stops_and_cleans_up_once() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request)
    adapter.complete_value = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        _run(request, None, adapter)
    assert adapter.complete_calls == 1
    assert adapter.cleanup_calls == 1


def test_caller_cancellation_during_cleanup_is_not_swallowed() -> None:
    async def scenario() -> None:
        request = _provider_request(None)
        cleanup_started = asyncio.Event()

        class SlowCleanupAdapter(FakeAdapter):
            async def cleanup(self) -> None:
                self.cleanup_calls += 1
                cleanup_started.set()
                await asyncio.Event().wait()

        adapter = SlowCleanupAdapter(request)
        task = asyncio.create_task(execute_provider_call(request, None, adapter))
        await cleanup_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert adapter.cleanup_calls == 1

    asyncio.run(scenario())


def test_caller_cancellation_during_stalled_stream_stops_pulls_and_cleans_up() -> None:
    async def scenario() -> None:
        request = _provider_request(None)
        pull_started = asyncio.Event()

        class StalledStreamAdapter(FakeAdapter):
            async def _stalled(self) -> AsyncIterator[ProviderAdapterStreamItem]:
                self.stream_pulls += 1
                pull_started.set()
                await asyncio.Event().wait()
                yield ProviderAdapterChunk("late")

            async def stream(
                self,
                request: ProviderExecutionRequest,
                input_payload: object,
            ) -> AsyncIterator[ProviderAdapterStreamItem]:
                return self._stalled()

        adapter = StalledStreamAdapter(request, mode="stream")
        task = asyncio.create_task(execute_provider_call(request, None, adapter))
        await pull_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert adapter.stream_pulls == 1
        assert adapter.cleanup_calls == 1

    asyncio.run(scenario())


def test_usage_and_decimal_cost_are_preserved_as_adapter_observations() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request)
    usage = ProviderUsageMetadata(unit_kind="tokens", input_units=2, output_units=3, total_units=5)
    cost = ProviderCostObservation(amount="0.1250", currency="USD", observed_at="2026-09-08T10:00:00Z")
    adapter.complete_value = ProviderAdapterComplete("answer", ("evidence/output.json",), usage, cost)

    outcome = _run(request, None, adapter)

    assert outcome.public_result.usage == usage
    assert outcome.public_result.cost == cost
    assert outcome.public_result.cost is not None
    assert str(outcome.public_result.cost.amount) == "0.1250"
    assert outcome.public_result.execution.cost_claimed is False


def test_public_evidence_is_deterministic_for_same_fixture_and_clock() -> None:
    request = _provider_request({"prompt": "hello"})
    first = _run(request, {"prompt": "hello"}, FakeAdapter(request))
    second = _run(request, {"prompt": "hello"}, FakeAdapter(request))

    assert first.public_result.model_dump(mode="json") == second.public_result.model_dump(mode="json")


def test_forged_request_and_malformed_stream_event_are_rejected() -> None:
    request = _provider_request(None)
    forged = request.model_copy(update={"credentials_included": True})
    with pytest.raises(ContractError, match="invalid_provider_request"):
        _run(forged, None, FakeAdapter(request))

    adapter = FakeAdapter(request, mode="stream")
    adapter.stream_values = [object()]
    with pytest.raises(ContractError, match="invalid_provider_event"):
        _run(request, None, adapter)


def test_generated_schemas_and_registry_validate_public_provider_call_models() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request)
    outcome = _run(request, None, adapter)
    registry = SchemaRegistry()
    descriptor_payload = adapter.descriptor.model_dump(mode="json")
    result_payload = outcome.public_result.model_dump(mode="json")

    for name, payload in (
        ("provider-call-adapter.v1", descriptor_payload),
        ("provider-call-result.v1", result_payload),
    ):
        schema = registry.load(name)
        Draft202012Validator.check_schema(schema)
        registry.validate(name, payload)

    forged = outcome.public_result.model_copy(update={"retry_attempts": 1})
    with pytest.raises(ContractError, match="contract_validation_failed"):
        registry.validate("provider-call-result.v1", forged.model_dump(mode="json"))

    for capabilities in ([], ["response_generation", "response_generation"]):
        invalid_descriptor = {**descriptor_payload, "capabilities": capabilities}
        with pytest.raises(ValidationError, match="capabilities"):
            TextProviderAdapterDescriptor.model_validate(invalid_descriptor)
        with pytest.raises(ContractError, match="contract_validation_failed"):
            registry.validate("provider-call-adapter.v1", invalid_descriptor)

    invalid_cleanup_result = {**result_payload, "cleanup_succeeded": None}
    with pytest.raises(ValidationError, match="cleanup_succeeded"):
        ProviderCallPublicResult.model_validate(invalid_cleanup_result)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        registry.validate("provider-call-result.v1", invalid_cleanup_result)


def test_malformed_failure_and_naive_clock_fail_as_contract_errors() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request)
    adapter.complete_value = ProviderAdapterFailure(
        code="synthetic_failure",
        category="provider",
        retryable=False,
        evidence_refs=(),
    )
    with pytest.raises(ContractError, match="invalid_provider_failure"):
        _run(request, None, adapter)

    naive = FakeAdapter(request)
    naive.clock.current = datetime(2026, 9, 8, 10, 0)
    with pytest.raises(ContractError, match="invalid_provider_clock"):
        _run(request, None, naive)


def test_custom_clock_and_malformed_success_do_not_expose_private_errors() -> None:
    request = _provider_request(None)

    class BrokenClock(FakeClock):
        def now(self) -> datetime:
            raise KeyError("private clock state")

    with pytest.raises(ContractError, match="invalid_provider_clock") as clock_error:
        _run(request, None, FakeAdapter(request, clock=BrokenClock()))
    assert "private clock state" not in str(clock_error.value)

    malformed = FakeAdapter(request)
    malformed.complete_value = ProviderAdapterComplete("answer", ())
    with pytest.raises(ContractError, match="invalid_provider_result") as result_error:
        _run(request, None, malformed)
    assert "answer" not in str(result_error.value)


@pytest.mark.parametrize(
    ("mode", "member"),
    [("complete", "complete"), ("stream", "stream"), ("complete", "cleanup")],
)
def test_raising_adapter_member_properties_are_redacted(mode: Literal["complete", "stream"], member: str) -> None:
    request = _provider_request(None)

    class RaisingMemberAdapter(FakeAdapter):
        def __getattribute__(self, name: str) -> object:
            if name == member:
                raise KeyError("PRIVATE_MEMBER_SENTINEL")
            return super().__getattribute__(name)

    with pytest.raises(ContractError, match="invalid_provider_adapter") as error:
        _run(request, None, RaisingMemberAdapter(request, mode=mode))
    assert "PRIVATE_MEMBER_SENTINEL" not in str(error.value)


@pytest.mark.parametrize("mode", ["complete", "stream"])
@pytest.mark.parametrize("field_name", ["usage", "cost"])
def test_malformed_and_forged_nested_adapter_evidence_is_rejected(
    mode: Literal["complete", "stream"],
    field_name: Literal["usage", "cost"],
) -> None:
    request = _provider_request(None)
    valid_usage = ProviderUsageMetadata(unit_kind="tokens", input_units=1, output_units=1, total_units=2)
    valid_cost = ProviderCostObservation(amount="0.25", currency="USD", observed_at="2026-09-08T10:00:00Z")
    malformed: object
    if field_name == "usage":
        malformed = valid_usage.model_copy(update={"total_units": 3})
    else:
        malformed = valid_cost.model_copy(update={"amount": "private-invalid-value"})

    for value in (cast(ProviderUsageMetadata, {"total_units": 1}), malformed):
        adapter = FakeAdapter(request, mode=mode)
        usage = value if field_name == "usage" else valid_usage
        cost = value if field_name == "cost" else valid_cost
        if mode == "complete":
            adapter.complete_value = ProviderAdapterComplete(
                "answer",
                ("evidence/output.json",),
                usage=cast(ProviderUsageMetadata, usage),
                cost=cast(ProviderCostObservation, cost),
            )
        else:
            adapter.stream_values = [
                ProviderAdapterChunk("answer"),
                ProviderAdapterTerminal(
                    ("evidence/output.json",),
                    usage=cast(ProviderUsageMetadata, usage),
                    cost=cast(ProviderCostObservation, cost),
                ),
            ]
        with pytest.raises(ContractError, match="invalid_provider_event") as error:
            _run(request, None, adapter)
        assert "private-invalid-value" not in str(error.value)
        assert "private-invalid-value" not in "".join(traceback.format_exception(error.value))
        assert adapter.cleanup_calls == 1


def test_stream_accepts_valid_usage_and_cost_neighbors() -> None:
    request = _provider_request(None)
    adapter = FakeAdapter(request, mode="stream")
    usage = ProviderUsageMetadata(unit_kind="tokens", input_units=1, output_units=1, total_units=2)
    cost = ProviderCostObservation(amount="0.25", currency="JPY", observed_at="2026-09-08T10:00:00Z")
    adapter.stream_values = [
        ProviderAdapterChunk("answer"),
        ProviderAdapterTerminal(("evidence/output.json",), usage=usage, cost=cost),
    ]

    outcome = _run(request, None, adapter)

    assert outcome.public_result.usage == usage
    assert outcome.public_result.cost == cost
