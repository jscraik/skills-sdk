"""Injected adapter protocols and private values for offline provider calls."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, TypeVar

from skills_sdk.models.provider_call import (
    ProviderCallPublicResult,
    ProviderCostObservation,
    TextProviderAdapterDescriptor,
)
from skills_sdk.models.provider_execution import ProviderExecutionRequest, ProviderUsageMetadata

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class ProviderCallLimits:
    """Caller-selected limits that may only tighten the SDK pilot defaults."""

    input_bytes: int = 262_144
    metadata_bytes: int = 65_536
    nesting_depth: int = 32
    output_bytes: int = 1_048_576
    chunk_bytes: int = 16_384
    events: int = 4_096
    buffered_events: int = 8
    overall_seconds: float = 30.0
    idle_seconds: float = 5.0
    cleanup_seconds: float = 1.0

    def __post_init__(self) -> None:
        defaults = DEFAULT_PROVIDER_CALL_LIMITS if "DEFAULT_PROVIDER_CALL_LIMITS" in globals() else self
        for field_name in (
            "input_bytes",
            "metadata_bytes",
            "nesting_depth",
            "output_bytes",
            "chunk_bytes",
            "events",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0 or value > getattr(defaults, field_name):
                raise ValueError(f"provider call {field_name} must be a positive tightening of the default")
        if (
            type(self.buffered_events) is not int
            or self.buffered_events < 0
            or self.buffered_events > defaults.buffered_events
        ):
            raise ValueError("provider call buffered_events must be a non-negative tightening of the default")
        for field_name in ("overall_seconds", "idle_seconds", "cleanup_seconds"):
            value = getattr(self, field_name)
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or value <= 0
                or value > getattr(defaults, field_name)
            ):
                raise ValueError(f"provider call {field_name} must be a positive tightening of the default")


DEFAULT_PROVIDER_CALL_LIMITS = ProviderCallLimits()


@dataclass(frozen=True, slots=True)
class ProviderAdapterComplete:
    text: str
    evidence_refs: tuple[str, ...]
    usage: ProviderUsageMetadata | None = None
    cost: ProviderCostObservation | None = None


@dataclass(frozen=True, slots=True)
class ProviderAdapterChunk:
    text: str


@dataclass(frozen=True, slots=True)
class ProviderAdapterTerminal:
    evidence_refs: tuple[str, ...]
    usage: ProviderUsageMetadata | None = None
    cost: ProviderCostObservation | None = None


ProviderAdapterStreamEvent = ProviderAdapterChunk | ProviderAdapterTerminal


@dataclass(frozen=True, slots=True)
class ProviderAdapterBatch:
    """One adapter pull containing buffered stream events in source order."""

    events: tuple[ProviderAdapterStreamEvent, ...]


ProviderAdapterStreamItem = ProviderAdapterStreamEvent | ProviderAdapterBatch


@dataclass(frozen=True, slots=True)
class ProviderCallOutcome:
    """Private output paired with redaction-safe public evidence."""

    public_result: ProviderCallPublicResult
    complete_text: str | None = None


class ProviderCallClock(Protocol):
    def now(self) -> datetime: ...

    async def wait_for(self, awaitable: Awaitable[_T], timeout_seconds: float) -> _T: ...


@dataclass(frozen=True, slots=True)
class AsyncioProviderCallClock:
    """SDK-owned production clock and timeout scheduler."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def wait_for(self, awaitable: Awaitable[_T], timeout_seconds: float) -> _T:
        task = asyncio.ensure_future(awaitable)
        done, _pending = await asyncio.wait({task}, timeout=timeout_seconds)
        if task in done:
            return task.result()
        task.cancel()
        task.add_done_callback(_consume_detached_task_result)
        raise TimeoutError


def _consume_detached_task_result[T](task: asyncio.Future[T]) -> None:
    """Consume a late task result after a deadline without accepting it."""

    if task.cancelled():
        return
    try:
        task.exception()
    except asyncio.CancelledError:
        return


DEFAULT_PROVIDER_CALL_CLOCK = AsyncioProviderCallClock()


class TextProviderAdapterBase(Protocol):
    descriptor: TextProviderAdapterDescriptor

    async def cleanup(self) -> None: ...


class CompleteTextProviderAdapter(TextProviderAdapterBase, Protocol):
    async def complete(
        self,
        request: ProviderExecutionRequest,
        input_payload: JsonValue,
    ) -> ProviderAdapterComplete: ...


class StreamingTextProviderAdapter(TextProviderAdapterBase, Protocol):
    def stream(
        self, request: ProviderExecutionRequest, input_payload: JsonValue
    ) -> AsyncIterator[ProviderAdapterStreamItem]: ...


type TextProviderAdapter = CompleteTextProviderAdapter | StreamingTextProviderAdapter


class ProviderAdapterFailure(Exception):
    """Redaction-safe expected adapter failure; exception text is never retained."""

    def __init__(
        self,
        *,
        code: str,
        category: Literal["provider", "adapter", "transport", "timeout", "policy", "unknown"],
        retryable: bool,
        evidence_refs: tuple[str, ...],
        status: Literal["failed", "blocked", "indeterminate"] = "failed",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.category = category
        self.retryable = retryable
        self.evidence_refs = evidence_refs
        self.status = status


__all__ = [
    "DEFAULT_PROVIDER_CALL_CLOCK",
    "DEFAULT_PROVIDER_CALL_LIMITS",
    "AsyncioProviderCallClock",
    "JsonValue",
    "ProviderAdapterBatch",
    "ProviderAdapterChunk",
    "ProviderAdapterComplete",
    "ProviderAdapterFailure",
    "ProviderAdapterStreamEvent",
    "ProviderAdapterStreamItem",
    "ProviderAdapterTerminal",
    "ProviderCallClock",
    "ProviderCallLimits",
    "ProviderCallOutcome",
    "TextProviderAdapter",
]
