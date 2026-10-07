"""Invoke one caller-selected offline review adapter on a bound source snapshot."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.models.content_review import ContentReviewExecutionResult
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.safety import PackageSafetyReviewer
from skills_sdk.validation.content_review import _finding, assess_content_review
from skills_sdk.validation.skill_package import SkillValidationPolicy, _scan_files, validate_skill_package


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


def _observe_task(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


async def _invoke(callback: Callable[[ContentReviewInput], Awaitable[object]], inputs: ContentReviewInput) -> object:
    return await callback(inputs)


async def _adapter_metadata(
    adapter: OfflineContentReviewAdapter,
) -> tuple[PackageSafetyReviewer, Callable[[ContentReviewInput], Awaitable[object]]]:
    """Observe caller-owned metadata through the same exception-isolating task boundary."""
    reviewer = PackageSafetyReviewer.model_validate(adapter.reviewer.model_dump(mode="json", warnings="error"))
    callback = adapter.review
    if reviewer.method not in {"manual_review", "static_analysis"} or not inspect.iscoroutinefunction(callback):
        raise ValueError("offline review requires a local asynchronous adapter")
    return reviewer, callback


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
    metadata = (await asyncio.gather(_adapter_metadata(adapter), return_exceptions=True))[0]
    if isinstance(metadata, BaseException):
        return _blocked_execution(
            candidate, "invalid_content_review_adapter", "select a trusted offline review adapter"
        )
    reviewer, callback = metadata
    documents = tuple(ContentReviewDocument(item.path, item.sha256, captured[item.path]) for item in files)
    inputs = ContentReviewInput(PackageCandidateIdentity.model_validate(candidate.model_dump(mode="json")), documents)
    task = asyncio.create_task(_invoke(callback, inputs))
    try:
        done, _pending = await asyncio.wait({task}, timeout=30)
    except asyncio.CancelledError:
        task.cancel()
        task.add_done_callback(_observe_task)
        raise
    if task not in done:
        task.cancel()
        task.add_done_callback(_observe_task)
        return _blocked_execution(
            candidate, "content_review_timeout", "offline review adapter exceeded its deadline", reviewer=reviewer
        )
    observed = (await asyncio.gather(task, return_exceptions=True))[0]
    if isinstance(observed, BaseException):
        return _blocked_execution(
            candidate, "content_review_adapter_failed", "offline review adapter failed", reviewer=reviewer
        )
    review = assess_content_review(package_root, source_revision=source_revision, assessment=observed)
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
