"""Explicit trusted-host review admission before the supplied-evidence executor.

These private host capabilities are not portable receipts or issuer discovery.
The host owns event retrieval, policy selection and restart-safe consumption.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Protocol

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.matched_admission import MatchedCaseExecution, MatchedVariantExecution
from skills_sdk.evaluation.matched_execution import execute_matched_lane
from skills_sdk.evaluation.matched_plugin_context import PluginExecutionContext
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.models.matched_execution import MatchedExecutionReceipt
from skills_sdk.models.matched_ingress import _canonical_matched_input
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.validation.plugin_evidence import verify_plugin_package_validation


@dataclass(frozen=True, slots=True)
class LocalReviewExpectation:
    """Host-selected source, native issuer/event and exact final-report commitment."""

    candidate: PackageCandidateIdentity
    files_sha256: str
    mode_manifest_sha256: str
    thread_id: str
    turn_id: str
    message_id: str
    event_sha256: str
    report_sha256: str
    completed_at: int


@dataclass(frozen=True, slots=True)
class LocalReviewPolicy:
    """One host-approved manual-source-review operation for an exact paired plan."""

    operation_id: str
    plan_sha256: str
    retrieved_at: float
    deadline: float
    reviews: tuple[LocalReviewExpectation, ...]
    purpose: str = "manual-source-review"


class LocalReviewHost(Protocol):
    """Trusted host integration; never select this capability from package data."""

    def resolve_review(self, expected: LocalReviewExpectation) -> bytes:
        """Return the exact independently retrieved native event, at most 256 KiB."""
        ...

    def consume(self, operation_id: str, policy_sha256: str) -> bool:
        """Atomically spend the operation across restart; True only for first use."""
        ...


@dataclass(frozen=True, slots=True)
class LocalReviewAuthority:
    """Keep trusted host policy and capabilities outside package-controlled data."""

    policy: LocalReviewPolicy
    host: LocalReviewHost


def _reject(code: str) -> ContractError:
    return ContractError(code, "Trusted local source-review admission was rejected.")


def _text(value: object, *, digest: bool = False) -> str:
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise _reject("local_review_invalid_policy")
    if digest and re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise _reject("local_review_invalid_policy")
    return value


def _candidate_key(value: object) -> tuple[str, str, str]:
    if type(value) is not PackageCandidateIdentity:
        raise _reject("local_review_invalid_candidate")
    return (_text(value.package_id), _text(value.source_revision), _text(value.content_sha256, digest=True))


def _expectation_data(value: LocalReviewExpectation) -> dict[str, object]:
    if type(value) is not LocalReviewExpectation:
        raise _reject("local_review_invalid_policy")
    if type(value.completed_at) is not int or value.completed_at < 0:
        raise _reject("local_review_invalid_policy")
    return {
        "candidate": _candidate_key(value.candidate),
        "files_sha256": _text(value.files_sha256, digest=True),
        "mode_manifest_sha256": _text(value.mode_manifest_sha256, digest=True),
        "thread_id": _text(value.thread_id),
        "turn_id": _text(value.turn_id),
        "message_id": _text(value.message_id),
        "event_sha256": _text(value.event_sha256, digest=True),
        "report_sha256": _text(value.report_sha256, digest=True),
        "completed_at": value.completed_at,
    }


def _policy_digest(policy: LocalReviewPolicy, plan: MatchedComparisonPlan) -> str:
    if type(policy) is not LocalReviewPolicy or policy.purpose != "manual-source-review":
        raise _reject("local_review_policy_required")
    for value in (policy.retrieved_at, policy.deadline):
        if type(value) not in (float, int) or not math.isfinite(value):
            raise _reject("local_review_invalid_policy")
    if not 0 < policy.deadline - policy.retrieved_at <= 600:
        raise _reject("local_review_invalid_policy")
    if not policy.retrieved_at <= time.time() <= policy.deadline:
        raise _reject("local_review_operation_expired")
    if _text(policy.plan_sha256, digest=True) != plan.digest:
        raise _reject("local_review_plan_mismatch")
    if type(policy.reviews) is not tuple or not 1 <= len(policy.reviews) <= 2:
        raise _reject("local_review_invalid_policy")
    data = [_expectation_data(item) for item in policy.reviews]
    return canonical_json_sha256(
        {
            "operation_id": _text(policy.operation_id),
            "plan_sha256": policy.plan_sha256,
            "retrieved_at": policy.retrieved_at,
            "deadline": policy.deadline,
            "purpose": policy.purpose,
            "reviews": data,
        }
    )


def _contexts(executions: tuple[MatchedCaseExecution, ...]) -> tuple[PluginExecutionContext, ...]:
    if type(executions) is not tuple or len(executions) != 10:
        raise _reject("local_review_invalid_batch")
    result = []
    for pair in executions:
        if type(pair) is not MatchedCaseExecution:
            raise _reject("local_review_invalid_batch")
        for item in (pair.baseline, pair.candidate):
            if type(item) is not MatchedVariantExecution or type(item.plugin_context) is not PluginExecutionContext:
                raise _reject("local_review_invalid_batch")
            result.append(item.plugin_context)
    return tuple(result)


def _check_sources(contexts: tuple[PluginExecutionContext, ...], policy: LocalReviewPolicy) -> None:
    by_candidate = {_candidate_key(item.candidate): item for item in policy.reviews}
    if len(by_candidate) != len(policy.reviews):
        raise _reject("local_review_duplicate_candidate")
    seen = set()
    for context in contexts:
        validation = context.validation
        key = _candidate_key(validation.candidate)
        expected = by_candidate.get(key)
        if expected is None:
            raise _reject("local_review_candidate_mismatch")
        fresh = verify_plugin_package_validation(
            context.root, validation, source_revision=key[1], policy=context.policy
        )
        if fresh.status != "pass" or fresh != validation:
            raise _reject("local_review_source_changed")
        if (
            canonical_json_sha256([item.model_dump(mode="json") for item in fresh.files]) != expected.files_sha256
            or fresh.mode_manifest_sha256 != expected.mode_manifest_sha256
        ):
            raise _reject("local_review_resources_mismatch")
        seen.add(key)
    if seen != set(by_candidate):
        raise _reject("local_review_unused_candidate")


def _unique_pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate event key")
        result[key] = value
    return result


def _event_message(raw: bytes, expected: LocalReviewExpectation) -> None:
    if type(raw) is not bytes or len(raw) > 262144 or hashlib.sha256(raw).hexdigest() != expected.event_sha256:
        raise _reject("local_review_transport_changed")
    event = json.loads(raw, object_pairs_hook=_unique_pairs)
    if type(event) is not dict or "policy" in event or "resolver" in event:
        raise _reject("local_review_invalid_origin")
    if event["thread"]["id"] != expected.thread_id or event["thread"]["kind"] != "codex":
        raise _reject("local_review_issuer_mismatch")
    turns = [turn for turn in event["turns"] if turn.get("id") == expected.turn_id]
    if len(turns) != 1:
        raise _reject("local_review_turn_mismatch")
    turn = turns[0]
    if turn["status"] != "completed" or turn["error"] is not None:
        raise _reject("local_review_incomplete")
    if type(turn["completedAt"]) is not int or turn["completedAt"] != expected.completed_at:
        raise _reject("local_review_completion_mismatch")
    if not 0 <= time.time() - expected.completed_at <= 3600:
        raise _reject("local_review_stale")
    messages = [item for item in turn["items"] if item.get("id") == expected.message_id]
    if len(messages) != 1:
        raise _reject("local_review_message_mismatch")
    message = messages[0]
    if message["type"] != "agentMessage" or message["phase"] != "final_answer" or type(message["text"]) is not str:
        raise _reject("local_review_not_final")
    if hashlib.sha256((message["text"] + "\n").encode()).hexdigest() != expected.report_sha256:
        raise _reject("local_review_report_mismatch")


async def execute_reviewed_matched_lane(
    plan: object,
    lane: str,
    calibrations: tuple[object, object],
    executions: tuple[MatchedCaseExecution, ...],
    *,
    authority: LocalReviewAuthority,
) -> MatchedExecutionReceipt:
    """Require host-authorised source review, then retain every existing execution gate.

    Host capability exceptions and uncertain consumption reject before executor
    access. Spending the operation is not compensated if later preflight fails.
    """
    try:
        if type(authority) is not LocalReviewAuthority:
            raise _reject("local_review_policy_required")
        policy, host = authority.policy, authority.host
        parsed = MatchedComparisonPlan.model_validate(_canonical_matched_input(plan))
        policy_digest = _policy_digest(policy, parsed)
        contexts = _contexts(executions)
        _check_sources(contexts, policy)
        for expected in policy.reviews:
            _event_message(host.resolve_review(expected), expected)
        _check_sources(contexts, policy)
        if _policy_digest(policy, parsed) != policy_digest:
            raise _reject("local_review_policy_changed")
        if host.consume(policy.operation_id, policy_digest) is not True:
            raise _reject("local_review_consumption_rejected")
        _check_sources(contexts, policy)
        for expected in policy.reviews:
            if not 0 <= time.time() - expected.completed_at <= 3600:
                raise _reject("local_review_stale")
        if _policy_digest(policy, parsed) != policy_digest:
            raise _reject("local_review_policy_changed")
    except ContractError:
        raise
    except (OSError, RuntimeError, AttributeError, KeyError, IndexError, TypeError, ValueError, RecursionError):
        raise _reject("local_review_admission_failed") from None
    return await execute_matched_lane(parsed, lane, calibrations, executions)


__all__ = [
    "LocalReviewAuthority",
    "LocalReviewExpectation",
    "LocalReviewHost",
    "LocalReviewPolicy",
    "execute_reviewed_matched_lane",
]
