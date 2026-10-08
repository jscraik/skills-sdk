"""Invoke one caller-selected offline review adapter on a bound source snapshot."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import multiprocessing
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.models.content_review import (
    CONTENT_REVIEW_ASSESSMENT_MAX_BYTES,
    ContentReviewAssessment,
    ContentReviewExecutionResult,
)
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.safety import PackageSafetyReviewer
from skills_sdk.validation.content_review import _finding, assess_content_review
from skills_sdk.validation.skill_package import SkillValidationPolicy, _scan_files, validate_skill_package

_REVIEW_TIMEOUT_SECONDS = 30.0
_REVIEW_STARTUP_TIMEOUT_SECONDS = 30.0
_REVIEW_WIRE_LIMIT = CONTENT_REVIEW_ASSESSMENT_MAX_BYTES + 65_536


class _OversizedReviewerMetadata(ValueError):
    """Invocation metadata cannot fit the bounded worker protocol."""


@dataclass(frozen=True, slots=True)
class ContentReviewDocument:
    """Private package bytes; never serialize source into a public result."""

    path: str
    sha256: str
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ContentReviewInput:
    """Untrusted source data, not instructions to the host or adapter."""

    candidate: PackageCandidateIdentity
    documents: tuple[ContentReviewDocument, ...] = field(repr=False)


class OfflineContentReviewAdapter(Protocol):
    """Trusted caller-owned offline code; the SDK does not load arbitrary plugins."""

    reviewer: PackageSafetyReviewer

    async def review(self, inputs: ContentReviewInput) -> object: ...


async def _invoke(
    callback: Callable[[ContentReviewInput], Awaitable[object]],
    inputs: ContentReviewInput,
    channel: socket.socket,
    reviewer: PackageSafetyReviewer,
) -> tuple[object, float]:
    invoked_at = time.monotonic()
    packet = {"kind": "invoked", "reviewer": reviewer.model_dump(mode="json"), "invoked_at": invoked_at}
    if len(json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1 > _REVIEW_WIRE_LIMIT:
        raise _OversizedReviewerMetadata("reviewer metadata exceeds the worker output limit")
    invocation = callback(inputs)
    _send_packet(channel, packet)
    result = await invocation
    return result, time.monotonic()


async def _adapter_metadata(
    adapter: OfflineContentReviewAdapter,
) -> tuple[PackageSafetyReviewer, Callable[[ContentReviewInput], Awaitable[object]]]:
    """Observe caller-owned metadata through the same exception-isolating task boundary."""
    reviewer = PackageSafetyReviewer.model_validate(adapter.reviewer.model_dump(mode="json", warnings="error"))
    callback = adapter.review
    if reviewer.method not in {"manual_review", "static_analysis"} or not inspect.iscoroutinefunction(callback):
        raise ValueError("offline review requires a local asynchronous adapter")
    return reviewer, callback


def _send_packet(channel: socket.socket, packet: dict[str, object]) -> None:
    payload = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > _REVIEW_WIRE_LIMIT:
        replacement: dict[str, object] = {"kind": "blocked", "code": "content_review_output_limit"}
        if "completed_at" in packet:
            replacement["completed_at"] = packet["completed_at"]
        payload = json.dumps(replacement, separators=(",", ":")).encode("utf-8") + b"\n"
    channel.sendall(payload)


async def _worker_review(
    channel: socket.socket, adapter: OfflineContentReviewAdapter, inputs: ContentReviewInput
) -> None:
    metadata = (await asyncio.gather(_adapter_metadata(adapter), return_exceptions=True))[0]
    if isinstance(metadata, BaseException):
        _send_packet(
            channel,
            {"kind": "blocked", "code": "invalid_content_review_adapter", "startup_completed_at": time.monotonic()},
        )
        return
    reviewer, callback = metadata
    observed = (await asyncio.gather(_invoke(callback, inputs, channel, reviewer), return_exceptions=True))[0]
    if isinstance(observed, _OversizedReviewerMetadata):
        _send_packet(
            channel,
            {"kind": "blocked", "code": "content_review_output_limit", "startup_completed_at": time.monotonic()},
        )
        return
    if isinstance(observed, BaseException):
        _send_packet(
            channel, {"kind": "blocked", "code": "content_review_adapter_failed", "completed_at": time.monotonic()}
        )
        return
    observed, completed_at = observed
    try:
        if isinstance(observed, ContentReviewAssessment) and type(observed) is not ContentReviewAssessment:
            raise ValueError("returned typed review must use the canonical assessment model")
        raw = (
            observed.model_dump(mode="python", warnings="error")
            if isinstance(observed, ContentReviewAssessment)
            else observed
        )
        assessment = ContentReviewAssessment.model_validate(raw)
        _send_packet(
            channel,
            {
                "kind": "returned",
                "assessment": assessment.model_dump(mode="json", warnings="error"),
                "completed_at": completed_at,
            },
        )
    except (ValidationError, ValueError, TypeError, RuntimeError, LookupError, PydanticSerializationError):
        _send_packet(channel, {"kind": "blocked", "code": "invalid_content_review", "completed_at": completed_at})


def _review_worker(channel: socket.socket, adapter: OfflineContentReviewAdapter, inputs: ContentReviewInput) -> None:
    """Run trusted caller code in a fresh interpreter, never in the parent loop."""
    try:
        asyncio.run(_worker_review(channel, adapter, inputs))
    finally:
        channel.close()


def _stop_worker(process: BaseProcess) -> None:
    """Bound cleanup of the SDK-owned process; do not wait on caller cooperation."""
    if process.pid is None:
        process.close()
        return
    process.join(timeout=0.05)
    if process.is_alive():
        process.terminate()
        process.join(timeout=0.1)
    if process.is_alive():
        process.kill()
        process.join(timeout=0.1)
    if not process.is_alive():
        process.close()


@dataclass(frozen=True, slots=True)
class _WorkerObservation:
    reviewer: PackageSafetyReviewer | None = None
    assessment: ContentReviewAssessment | None = None
    code: str | None = None


async def _read_worker(channel: socket.socket, launched_at: float) -> _WorkerObservation:
    loop = asyncio.get_running_loop()
    reviewer: PackageSafetyReviewer | None = None
    invoked_at = 0.0
    pending = bytearray()
    try:
        startup_remaining = launched_at + _REVIEW_STARTUP_TIMEOUT_SECONDS - time.monotonic()
        async with asyncio.timeout(max(0.0, startup_remaining)) as deadline:
            while True:
                chunk = await loop.sock_recv(channel, 65_536)
                if not chunk:
                    return _WorkerObservation(reviewer, code="content_review_adapter_failed")
                pending.extend(chunk)
                if len(pending) > _REVIEW_WIRE_LIMIT and b"\n" not in pending:
                    return _WorkerObservation(reviewer, code="content_review_output_limit")
                while b"\n" in pending:
                    line, _, remaining = pending.partition(b"\n")
                    pending = bytearray(remaining)
                    if len(line) + 1 > _REVIEW_WIRE_LIMIT:
                        return _WorkerObservation(reviewer, code="content_review_output_limit")
                    packet = json.loads(line)
                    if not isinstance(packet, dict):
                        raise ValueError("invalid worker packet")
                    if packet.get("kind") == "invoked" and reviewer is None:
                        reviewer = PackageSafetyReviewer.model_validate(packet["reviewer"])
                        invoked_at = float(packet["invoked_at"])
                        if not math.isfinite(invoked_at):
                            raise ValueError("invalid worker invocation time")
                        if invoked_at - launched_at > _REVIEW_STARTUP_TIMEOUT_SECONDS:
                            return _WorkerObservation(reviewer, code="content_review_timeout")
                        remaining = invoked_at + _REVIEW_TIMEOUT_SECONDS - time.monotonic()
                        deadline.reschedule(loop.time() + remaining)
                    elif packet.get("kind") in {"returned", "blocked"} and reviewer is not None:
                        completed_at = float(packet["completed_at"])
                        if not math.isfinite(completed_at) or completed_at < invoked_at:
                            raise ValueError("invalid worker completion time")
                        if completed_at - invoked_at > _REVIEW_TIMEOUT_SECONDS:
                            return _WorkerObservation(reviewer, code="content_review_timeout")
                        if packet["kind"] == "blocked":
                            return _WorkerObservation(reviewer, code=str(packet["code"]))
                        return _WorkerObservation(
                            reviewer, ContentReviewAssessment.model_validate(packet["assessment"])
                        )
                    elif packet.get("kind") == "blocked":
                        completed_at = float(packet["startup_completed_at"])
                        if not math.isfinite(completed_at):
                            raise ValueError("invalid worker startup completion time")
                        if completed_at - launched_at > _REVIEW_STARTUP_TIMEOUT_SECONDS:
                            return _WorkerObservation(code="content_review_timeout")
                        return _WorkerObservation(reviewer, code=str(packet["code"]))
                    else:
                        raise ValueError("invalid worker transition")
    except TimeoutError:
        return _WorkerObservation(reviewer, code="content_review_timeout")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return _WorkerObservation(reviewer, code="content_review_adapter_failed")


async def _isolated_review(adapter: OfflineContentReviewAdapter, inputs: ContentReviewInput) -> _WorkerObservation:
    if multiprocessing.current_process().daemon:
        return _WorkerObservation(code="unsupported_content_review_isolation")
    try:
        parent, child = socket.socketpair()
    except OSError:
        return _WorkerObservation(code="unsupported_content_review_isolation")
    parent.setblocking(False)
    process = multiprocessing.get_context("spawn").Process(target=_review_worker, args=(child, adapter, inputs))
    try:

        async def start_worker() -> float:
            """Capture caller-owned transfer failures through the existing task boundary."""
            process.start()
            return time.monotonic()

        transfer = (await asyncio.gather(start_worker(), return_exceptions=True))[0]
        if isinstance(transfer, BaseException):
            return _WorkerObservation(code="unsupported_content_review_isolation")
        child.close()
        return await _read_worker(parent, transfer)
    finally:
        parent.close()
        child.close()
        _stop_worker(process)


def _blocked_execution(
    candidate: PackageCandidateIdentity | None,
    code: str,
    message: str,
    *,
    reviewer: PackageSafetyReviewer | None = None,
) -> ContentReviewExecutionResult:
    return ContentReviewExecutionResult(
        candidate=candidate,
        status="blocked",
        adapter_invoked=reviewer is not None,
        reviewer=reviewer,
        findings=(_finding(code, message),),
    )


async def execute_content_review(
    package_root: Path, *, source_revision: str, adapter: OfflineContentReviewAdapter
) -> ContentReviewExecutionResult:
    """Observe a bounded offline callback; callers own its trust and side effects."""
    validation = validate_skill_package(package_root, source_revision=source_revision)
    candidate = validation.candidate
    if validation.status != "pass" or candidate is None:
        return ContentReviewExecutionResult(candidate=candidate, status="blocked", findings=validation.findings)
    files, findings, captured = _scan_files(package_root.absolute(), SkillValidationPolicy())
    if findings or candidate_content_sha256(files) != candidate.content_sha256:
        return _blocked_execution(candidate, "content_review_candidate_changed", "candidate changed before review")
    if sum(len(payload) for payload in captured.values()) > 8_388_608:
        return _blocked_execution(
            candidate, "content_review_input_limit", "offline review source exceeds the eight MiB limit"
        )
    documents = tuple(ContentReviewDocument(item.path, item.sha256, captured[item.path]) for item in files)
    inputs = ContentReviewInput(PackageCandidateIdentity.model_validate(candidate.model_dump(mode="json")), documents)
    observed = await _isolated_review(adapter, inputs)
    reviewer = observed.reviewer
    if observed.code is not None:
        return _blocked_execution(
            candidate, observed.code, "offline review could not complete safely", reviewer=reviewer
        )
    review = assess_content_review(package_root, source_revision=source_revision, assessment=observed.assessment)
    execution_findings = list(review.findings)
    if review.candidate != candidate:
        execution_findings.append(_finding("content_review_candidate_changed", "candidate changed during review"))
    if review.assessment is not None and review.assessment.reviewer != reviewer:
        execution_findings.append(_finding("content_review_reviewer_mismatch", "adapter returned a different reviewer"))
    assessment_digest = canonical_json_sha256(review.assessment.model_dump(mode="json")) if review.assessment else None
    return ContentReviewExecutionResult(
        candidate=candidate,
        status="blocked" if execution_findings else "pass",
        adapter_invoked=True,
        reviewer=reviewer,
        review=review,
        assessment_sha256=assessment_digest,
        findings=tuple(execution_findings),
    )


__all__ = ["ContentReviewDocument", "ContentReviewInput", "OfflineContentReviewAdapter", "execute_content_review"]
