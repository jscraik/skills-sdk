"""Bounded orchestration for one injected offline text-provider adapter."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
from asyncio import CancelledError, gather
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, cast

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_call import (
    ProviderCallPublicResult,
    ProviderCostObservation,
    TextProviderAdapterDescriptor,
)
from skills_sdk.models.provider_execution import (
    ProviderExecutionBlocker,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderUsageMetadata,
)
from skills_sdk.providers.types import (
    DEFAULT_PROVIDER_CALL_CLOCK,
    DEFAULT_PROVIDER_CALL_LIMITS,
    JsonValue,
    ProviderAdapterBatch,
    ProviderAdapterChunk,
    ProviderAdapterComplete,
    ProviderAdapterFailure,
    ProviderAdapterStreamItem,
    ProviderAdapterTerminal,
    ProviderCallClock,
    ProviderCallLimits,
    ProviderCallOutcome,
    TextProviderAdapter,
)


@dataclass(frozen=True, slots=True)
class _Terminal:
    status: Literal["completed", "failed", "blocked", "indeterminate"]
    text: str | None
    output_sha256: str | None
    event_sha256: str
    event_count: int
    max_buffered_events: int
    usage: ProviderUsageMetadata | None
    cost: ProviderCostObservation | None
    evidence_refs: tuple[str, ...]
    blocker: ProviderExecutionBlocker | None = None
    error: ProviderExecutionError | None = None


@dataclass(frozen=True, slots=True)
class _AdapterBindings:
    descriptor: TextProviderAdapterDescriptor
    complete: Callable[[ProviderExecutionRequest, JsonValue], Awaitable[ProviderAdapterComplete]] | None
    stream: Callable[[ProviderExecutionRequest, JsonValue], Awaitable[AsyncIterator[ProviderAdapterStreamItem]]] | None
    cleanup: Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class _ClockBindings:
    now: Callable[[], datetime]
    wait_for: Callable[[Awaitable[object], float], Awaitable[object]]


@dataclass(slots=True)
class _StreamState:
    chunks: list[str] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)
    total_bytes: int = 0
    max_buffered_events: int = 0


def _contract_error(code: str, message: str) -> ContractError:
    return ContractError(code, message)


def _normalize_json(value: object, *, depth: int, maximum_depth: int, active: set[int]) -> JsonValue:
    if depth > maximum_depth:
        raise _contract_error("provider_input_depth_exceeded", "provider input exceeds the nesting-depth limit")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise _contract_error("invalid_provider_input", "provider input strings must be valid UTF-8") from None
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _contract_error("invalid_provider_input", "provider input contains a non-finite number")
        return value
    if isinstance(value, list | dict):
        identity = id(value)
        if identity in active:
            raise _contract_error("invalid_provider_input", "provider input contains a cyclic container")
        active.add(identity)
        try:
            if isinstance(value, list):
                return [
                    _normalize_json(item, depth=depth + 1, maximum_depth=maximum_depth, active=active) for item in value
                ]
            if not all(isinstance(key, str) for key in value):
                raise _contract_error("invalid_provider_input", "provider input object keys must be strings")
            try:
                for key in value:
                    key.encode("utf-8")
            except UnicodeEncodeError:
                raise _contract_error("invalid_provider_input", "provider input keys must be valid UTF-8") from None
            return {
                key: _normalize_json(item, depth=depth + 1, maximum_depth=maximum_depth, active=active)
                for key, item in value.items()
            }
        finally:
            active.remove(identity)
    raise _contract_error("invalid_provider_input", "provider input must contain only JSON-compatible values")


def _canonical_bytes(value: JsonValue) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate_request_and_input(
    request: ProviderExecutionRequest,
    input_payload: JsonValue,
    limits: ProviderCallLimits,
) -> tuple[ProviderExecutionRequest, JsonValue]:
    try:
        request = ProviderExecutionRequest.model_validate(request)
    except ValidationError:
        raise _contract_error("invalid_provider_request", "provider request failed revalidation") from None
    if request.status != "prepared":
        raise _contract_error(
            "unsupported_provider_request",
            "provider call requires a prepared request",
        )
    normalized = _normalize_json(input_payload, depth=0, maximum_depth=limits.nesting_depth, active=set())
    payload_bytes = _canonical_bytes(normalized)
    if len(payload_bytes) > limits.input_bytes:
        raise _contract_error("provider_input_too_large", "provider input exceeds the byte limit")
    if (
        isinstance(normalized, dict)
        and "metadata" in normalized
        and len(_canonical_bytes(cast(JsonValue, normalized["metadata"]))) > limits.metadata_bytes
    ):
        raise _contract_error("provider_metadata_too_large", "provider metadata exceeds the byte limit")
    if canonical_json_sha256(normalized) != request.input_sha256:
        raise _contract_error("provider_input_digest_mismatch", "provider input digest does not match the request")
    return request, normalized


def _validate_adapter(
    request: ProviderExecutionRequest,
    raw_descriptor: object,
    raw_members: tuple[object, object],
) -> _AdapterBindings:
    try:
        descriptor = TextProviderAdapterDescriptor.model_validate(raw_descriptor)
        provider = ProviderIdentityV2.model_validate(descriptor.provider.model_dump(mode="json"))
    except (AttributeError, ValidationError):
        raise _contract_error("invalid_provider_adapter", "provider adapter descriptor failed revalidation") from None
    if provider != request.provider:
        raise _contract_error("provider_adapter_mismatch", "provider adapter identity does not match the request")
    raw_selected, raw_cleanup = raw_members
    if not callable(raw_cleanup):
        raise _contract_error("invalid_provider_adapter", "provider adapter does not implement cleanup")
    if not callable(raw_selected):
        raise _contract_error("invalid_provider_adapter", "provider adapter does not implement its selected mode")
    if descriptor.mode == "stream" and not inspect.iscoroutinefunction(raw_selected):
        raise _contract_error("invalid_provider_adapter", "provider stream factory must be asynchronous")
    return _AdapterBindings(
        descriptor=descriptor,
        complete=cast(Callable[[ProviderExecutionRequest, JsonValue], Awaitable[ProviderAdapterComplete]], raw_selected)
        if descriptor.mode == "complete"
        else None,
        stream=cast(
            Callable[[ProviderExecutionRequest, JsonValue], Awaitable[AsyncIterator[ProviderAdapterStreamItem]]],
            raw_selected,
        )
        if descriptor.mode == "stream"
        else None,
        cleanup=cast(Callable[[], Awaitable[None]], raw_cleanup),
    )


async def _read_adapter(adapter: TextProviderAdapter, request: ProviderExecutionRequest) -> _AdapterBindings:
    async def read() -> tuple[object, tuple[object, object]]:
        descriptor = adapter.descriptor
        mode = getattr(descriptor, "mode", None)
        selected = getattr(adapter, mode, None) if mode in {"complete", "stream"} else None
        return descriptor, (selected, adapter.cleanup)

    observed = await _captured(read())
    if isinstance(observed, BaseException):
        raise _contract_error("invalid_provider_adapter", "provider adapter members could not be read") from None
    if not isinstance(observed, tuple) or len(observed) != 2 or not isinstance(observed[1], tuple):
        raise _contract_error("invalid_provider_adapter", "provider adapter members are invalid")
    return _validate_adapter(request, observed[0], observed[1])


def _event_digest(events: list[dict[str, object]]) -> str:
    return canonical_json_sha256(events)


def _utf8_bytes(text: str) -> bytes:
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        raise _contract_error("invalid_provider_event", "provider text must be valid UTF-8") from None


def _text_digest(text: str) -> str:
    return hashlib.sha256(_utf8_bytes(text)).hexdigest()


async def _captured(awaitable: Awaitable[object]) -> object:
    values = await gather(awaitable, return_exceptions=True)
    return values[0]


async def _read_clock_bindings(clock: object) -> _ClockBindings:
    async def read() -> object:
        return clock.now, clock.wait_for

    observed = await _captured(read())
    if (
        isinstance(observed, BaseException)
        or not isinstance(observed, tuple)
        or len(observed) != 2
        or not all(callable(member) for member in observed)
    ):
        raise _contract_error("invalid_provider_clock", "provider clock members are invalid") from None
    return _ClockBindings(
        now=cast(Callable[[], datetime], observed[0]),
        wait_for=cast(Callable[[Awaitable[object], float], Awaitable[object]], observed[1]),
    )


async def _read_clock(now: Callable[[], datetime]) -> datetime:
    async def read() -> object:
        return now()

    value = await _captured(read())
    if isinstance(value, BaseException):
        raise _contract_error("invalid_provider_clock", "provider adapter clock failed") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _contract_error("invalid_provider_clock", "provider adapter clock must return an aware datetime")
    return value


def _close_awaitable(awaitable: object) -> None:
    if inspect.iscoroutine(awaitable):
        awaitable.close()
    elif isinstance(awaitable, asyncio.Future):
        awaitable.cancel()


async def _clock_wait_for(clock: _ClockBindings, awaitable: Awaitable[object], timeout_seconds: float) -> object:
    async def schedule() -> object:
        return clock.wait_for(awaitable, timeout_seconds)

    scheduled = await _captured(schedule())
    if isinstance(scheduled, BaseException):
        _close_awaitable(awaitable)
        raise _contract_error("invalid_provider_clock", "provider clock scheduler failed") from None
    if not inspect.isawaitable(scheduled):
        _close_awaitable(awaitable)
        raise _contract_error("invalid_provider_clock", "provider clock scheduler must return an awaitable")
    return await scheduled


def _validate_complete(value: object, limits: ProviderCallLimits) -> ProviderAdapterComplete:
    if not isinstance(value, ProviderAdapterComplete) or not isinstance(value.text, str):
        raise _contract_error("invalid_provider_event", "complete adapter returned an invalid result")
    if len(_utf8_bytes(value.text)) > limits.output_bytes:
        raise _contract_error("provider_output_too_large", "provider output exceeds the byte limit")
    return ProviderAdapterComplete(
        text=value.text,
        evidence_refs=value.evidence_refs,
        usage=_validate_usage(value.usage),
        cost=_validate_cost(value.cost),
    )


def _validate_usage(value: object) -> ProviderUsageMetadata | None:
    if value is None:
        return None
    if isinstance(value, ProviderUsageMetadata):
        try:
            value = value.model_dump(mode="json", warnings="none")
        except (PydanticSerializationError, TypeError, ValueError):
            raise _contract_error("invalid_provider_event", "provider usage evidence failed validation") from None
    try:
        return ProviderUsageMetadata.model_validate(value)
    except ValidationError:
        raise _contract_error("invalid_provider_event", "provider usage evidence failed validation") from None


def _validate_cost(value: object) -> ProviderCostObservation | None:
    if value is None:
        return None
    if isinstance(value, ProviderCostObservation):
        try:
            value = value.model_dump(mode="json", warnings="none")
        except (PydanticSerializationError, TypeError, ValueError):
            raise _contract_error("invalid_provider_event", "provider cost evidence failed validation") from None
    try:
        return ProviderCostObservation.model_validate(value)
    except ValidationError:
        raise _contract_error("invalid_provider_event", "provider cost evidence failed validation") from None


async def _run_complete(
    request: ProviderExecutionRequest,
    input_payload: JsonValue,
    adapter: _AdapterBindings,
    limits: ProviderCallLimits,
) -> _Terminal:
    if adapter.complete is None:
        raise _contract_error("invalid_provider_adapter", "provider adapter does not implement its selected mode")
    result = _validate_complete(await adapter.complete(request, input_payload), limits)
    output_sha256 = _text_digest(result.text)
    events = [{"kind": "complete", "sequence": 0, "bytes": len(_utf8_bytes(result.text)), "sha256": output_sha256}]
    return _Terminal(
        status="completed",
        text=result.text,
        output_sha256=output_sha256,
        event_sha256=_event_digest(events),
        event_count=1,
        max_buffered_events=0,
        usage=result.usage,
        cost=result.cost,
        evidence_refs=result.evidence_refs,
    )


async def _run_stream(
    request: ProviderExecutionRequest,
    input_payload: JsonValue,
    adapter: _AdapterBindings,
    limits: ProviderCallLimits,
    clock: _ClockBindings,
) -> _Terminal:
    if adapter.stream is None:
        raise _contract_error("invalid_provider_adapter", "provider adapter does not implement its selected mode")
    stream = await adapter.stream(request, input_payload)
    try:
        iterator = stream.__aiter__()
        next_event = iterator.__anext__
    except (AttributeError, TypeError):
        raise _contract_error("invalid_provider_adapter", "provider stream must return an async iterator") from None
    if not callable(next_event):
        raise _contract_error("invalid_provider_adapter", "provider stream must return an async iterator")
    state = _StreamState()
    while len(state.events) < limits.events:
        try:
            pull = next_event()
            if not inspect.isawaitable(pull):
                raise _contract_error("invalid_provider_adapter", "provider stream pulls must be awaitable")
            item = cast(ProviderAdapterStreamItem, await _clock_wait_for(clock, pull, limits.idle_seconds))
        except TimeoutError as error:
            raise ProviderAdapterFailure(
                code="provider_idle_timeout",
                category="timeout",
                retryable=True,
                evidence_refs=("provider-call/idle-timeout",),
            ) from error
        except StopAsyncIteration as error:
            raise _contract_error(
                "provider_stream_missing_terminal",
                "provider stream ended without a terminal event",
            ) from error
        if isinstance(item, ProviderAdapterBatch) and not isinstance(item.events, tuple):
            raise _contract_error("invalid_provider_event", "provider stream batch has an invalid event container")
        buffered = list(item.events) if isinstance(item, ProviderAdapterBatch) else [item]
        if isinstance(item, ProviderAdapterBatch) and (
            not buffered or limits.buffered_events == 0 or len(buffered) > limits.buffered_events
        ):
            raise _contract_error("provider_buffer_limit_exceeded", "provider stream batch exceeds the buffer limit")
        observed_buffer = len(buffered) if isinstance(item, ProviderAdapterBatch) else 0
        state.max_buffered_events = max(state.max_buffered_events, observed_buffer)
        terminal = _consume_events(buffered, state, limits)
        if terminal is not None:
            return terminal
    raise _contract_error("provider_event_limit_exceeded", "provider stream exceeds the event limit")


def _consume_events(
    buffered: list[object],
    state: _StreamState,
    limits: ProviderCallLimits,
) -> _Terminal | None:
    for index, event in enumerate(buffered):
        if len(state.events) >= limits.events:
            raise _contract_error("provider_event_limit_exceeded", "provider stream exceeds the event limit")
        if isinstance(event, ProviderAdapterChunk):
            _consume_chunk(event, state, limits)
            continue
        if isinstance(event, ProviderAdapterTerminal):
            if index != len(buffered) - 1:
                raise _contract_error(
                    "provider_event_after_terminal", "provider stream batch contains an event after terminal"
                )
            text = "".join(state.chunks)
            state.events.append({"kind": "terminal", "sequence": len(state.events), "status": "completed"})
            return _Terminal(
                status="completed",
                text=text,
                output_sha256=_text_digest(text),
                event_sha256=_event_digest(state.events),
                event_count=len(state.events),
                max_buffered_events=state.max_buffered_events,
                usage=_validate_usage(event.usage),
                cost=_validate_cost(event.cost),
                evidence_refs=event.evidence_refs,
            )
        raise _contract_error("invalid_provider_event", "provider stream returned an unsupported event")
    return None


def _consume_chunk(
    event: ProviderAdapterChunk,
    state: _StreamState,
    limits: ProviderCallLimits,
) -> None:
    if not isinstance(event.text, str):
        raise _contract_error("invalid_provider_event", "provider stream chunk must contain text")
    chunk_bytes = _utf8_bytes(event.text)
    if len(chunk_bytes) > limits.chunk_bytes:
        raise _contract_error("provider_chunk_too_large", "provider stream chunk exceeds the byte limit")
    if state.total_bytes + len(chunk_bytes) > limits.output_bytes:
        raise _contract_error("provider_output_too_large", "provider output exceeds the byte limit")
    state.total_bytes += len(chunk_bytes)
    state.chunks.append(event.text)
    state.events.append(
        {
            "kind": "chunk",
            "sequence": len(state.events),
            "bytes": len(chunk_bytes),
            "sha256": hashlib.sha256(chunk_bytes).hexdigest(),
        }
    )


def _failure_terminal(failure: ProviderAdapterFailure) -> _Terminal:
    event_sha256 = _event_digest([{"kind": "terminal", "sequence": 0, "status": failure.status}])
    try:
        if failure.status == "blocked":
            blocker = ProviderExecutionBlocker(
                code=failure.code,
                category="transport" if failure.category == "timeout" else failure.category,
                evidence_refs=failure.evidence_refs,
            )
            return _Terminal(
                "blocked", None, None, event_sha256, 1, 0, None, None, failure.evidence_refs, blocker=blocker
            )
        error = ProviderExecutionError(
            code=failure.code,
            category=failure.category,
            retryable=failure.retryable,
            evidence_refs=failure.evidence_refs,
        )
        return _Terminal(failure.status, None, None, event_sha256, 1, 0, None, None, failure.evidence_refs, error=error)
    except ValidationError:
        raise _contract_error("invalid_provider_failure", "provider failure evidence failed validation") from None


def _execution_result(
    request: ProviderExecutionRequest,
    terminal: _Terminal,
    started_at: datetime,
    finished_at: datetime,
) -> ProviderExecutionResult:
    try:
        result = ProviderExecutionResult.model_validate(
            {
                "schema_version": "provider-execution-result/v1",
                "result_id": f"{request.request_id}.result",
                "request_id": request.request_id,
                "request_sha256": canonical_json_sha256(request.model_dump(mode="json")),
                "idempotency_key_sha256": request.idempotency_key_sha256,
                "candidate": request.candidate.model_dump(mode="json"),
                "scenario_set_id": request.scenario_set_id,
                "case_id": request.case_id,
                "provider": request.provider.model_dump(mode="json"),
                "status": terminal.status,
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
                "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
                "output_sha256": terminal.output_sha256,
                "usage": terminal.usage.model_dump(mode="json") if terminal.usage else None,
                "evidence_refs": terminal.evidence_refs,
                "blocker": terminal.blocker.model_dump(mode="json") if terminal.blocker else None,
                "error": terminal.error.model_dump(mode="json") if terminal.error else None,
                "sdk_execution_performed": False,
                "credentials_retained": False,
                "raw_payloads_retained": False,
                "cost_claimed": False,
            }
        )
        return result.validate_against_request(request)
    except (ValidationError, ValueError):
        raise _contract_error("invalid_provider_result", "provider result evidence failed validation") from None


async def _cleanup(adapter: _AdapterBindings, limits: ProviderCallLimits, clock: _ClockBindings) -> bool:
    async def cleanup() -> object:
        cleanup_call = adapter.cleanup()
        if not inspect.isawaitable(cleanup_call):
            raise _contract_error("invalid_provider_adapter", "provider cleanup must return an awaitable")
        return await _clock_wait_for(clock, cleanup_call, limits.cleanup_seconds)

    observed = await _captured(cleanup())
    if isinstance(observed, CancelledError):
        raise observed
    if isinstance(observed, ContractError):
        raise observed
    if not isinstance(observed, BaseException) and observed is not None:
        raise _contract_error("invalid_provider_adapter", "provider cleanup must resolve to None")
    return not isinstance(observed, BaseException)


def _terminal_from_observed(observed: object) -> _Terminal:
    if isinstance(observed, _Terminal):
        return observed
    if isinstance(observed, ProviderAdapterFailure):
        return _failure_terminal(observed)
    if isinstance(observed, TimeoutError):
        return _failure_terminal(
            ProviderAdapterFailure(
                code="provider_call_timeout",
                category="timeout",
                retryable=True,
                evidence_refs=("provider-call/timeout",),
            )
        )
    if isinstance(observed, ContractError):
        raise observed
    if isinstance(observed, CancelledError):
        raise observed
    if isinstance(observed, BaseException):
        return _failure_terminal(
            ProviderAdapterFailure(
                code="provider_call_indeterminate",
                category="unknown",
                retryable=False,
                evidence_refs=("provider-call/indeterminate",),
                status="indeterminate",
            )
        )
    raise _contract_error("invalid_provider_adapter", "provider adapter returned no terminal outcome")


async def execute_provider_call(
    request: ProviderExecutionRequest,
    input_payload: JsonValue,
    adapter: TextProviderAdapter,
    *,
    limits: ProviderCallLimits = DEFAULT_PROVIDER_CALL_LIMITS,
    clock: ProviderCallClock = DEFAULT_PROVIDER_CALL_CLOCK,
) -> ProviderCallOutcome:
    """Execute one bounded offline provider call through an injected adapter."""

    if type(limits) is not ProviderCallLimits:
        raise _contract_error("invalid_provider_limits", "provider call limits failed validation")
    try:
        limits.__post_init__()
    except ValueError:
        raise _contract_error("invalid_provider_limits", "provider call limits failed validation") from None
    request, input_payload = _validate_request_and_input(request, input_payload, limits)
    clock_bindings = await _read_clock_bindings(clock)
    bindings = await _read_adapter(adapter, request)
    descriptor = bindings.descriptor
    try:
        started_at = await _read_clock(clock_bindings.now)
        if request.declared_capability != "response_generation":
            terminal = _failure_terminal(
                ProviderAdapterFailure(
                    code="unsupported_provider_capability",
                    category="adapter",
                    retryable=False,
                    evidence_refs=("provider-call/capability",),
                    status="blocked",
                )
            )
        else:
            runner = _run_complete if descriptor.mode == "complete" else _run_stream

            async def run() -> object:
                runner_call = (
                    runner(request, input_payload, bindings, limits, clock_bindings)
                    if descriptor.mode == "stream"
                    else runner(request, input_payload, bindings, limits)
                )
                return await _clock_wait_for(
                    clock_bindings,
                    runner_call,
                    limits.overall_seconds,
                )

            observed = await _captured(run())
            terminal = _terminal_from_observed(observed)
    finally:
        cleanup_succeeded = await _cleanup(bindings, limits, clock_bindings)
    finished_at = await _read_clock(clock_bindings.now)
    execution = _execution_result(request, terminal, started_at, finished_at)
    try:
        public_result = ProviderCallPublicResult(
            request_id=request.request_id,
            mode=descriptor.mode,
            status=terminal.status,
            event_count=terminal.event_count,
            output_bytes=len(_utf8_bytes(terminal.text)) if terminal.text is not None else 0,
            output_sha256=terminal.output_sha256,
            event_sha256=terminal.event_sha256,
            max_buffered_events=terminal.max_buffered_events,
            cleanup_attempted=True,
            cleanup_succeeded=cleanup_succeeded,
            cleanup_error_code=None if cleanup_succeeded else "cleanup_failed",
            usage=terminal.usage,
            cost=terminal.cost,
            execution=execution,
        )
    except ValidationError:
        raise _contract_error("invalid_provider_result", "provider result evidence failed validation") from None
    return ProviderCallOutcome(public_result=public_result, complete_text=terminal.text)


__all__ = ["execute_provider_call"]
