"""Run one selected case through injected provider and semantic-judge adapters."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import re
from asyncio import CancelledError, gather
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Protocol, cast

from pydantic_core import PydanticSerializationError

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.deterministic_v2 import evaluate_scenario_set_v2
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput, assess_pre_execution_safety
from skills_sdk.evaluation.selected_case import (
    SelectedCaseDefinition,
    SemanticAssertion,
    _blocked_observation,
    _canonical_input_payload,
    _request_matches_definition,
    _revalidate_definition,
    _validated_judge_artifact,
    _validated_observation,
)
from skills_sdk.models.evaluation_v2 import EvaluationReceiptV2
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.safety import _public_text_is_redaction_safe
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence
from skills_sdk.providers import (
    DEFAULT_PROVIDER_CALL_CLOCK,
    DEFAULT_PROVIDER_CALL_LIMITS,
    JsonValue,
    ProviderCallLimits,
    TextProviderAdapter,
    execute_provider_call,
)


@dataclass(frozen=True, slots=True)
class SelectedCaseJudgeInput:
    """Private actual output and public identities supplied to one host judge."""

    request: ProviderExecutionRequest
    output_text: str = field(repr=False)
    output_sha256: str
    assertion_contract_sha256: str
    assertions: tuple[SemanticAssertion, ...]


class SelectedCaseJudgeAdapter(Protocol):
    """Host-owned judge that returns evidence for the actual provider output."""

    identity: ProviderIdentityV2

    async def judge(self, inputs: SelectedCaseJudgeInput) -> object: ...

    async def cleanup(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _JudgeBindings:
    identity: ProviderIdentityV2
    judge: Callable[[SelectedCaseJudgeInput], Awaitable[object]]
    cleanup: Callable[[], Awaitable[None]]


def _blocked(
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    code: str,
    evidence_refs: tuple[str, ...] = (),
    *,
    runner: ProviderIdentityV2 | None = None,
) -> EvaluationReceiptV2:
    if type(code) is not str or re.fullmatch(r"[a-z0-9_]+", code) is None or not _public_text_is_redaction_safe(code):
        code = "invalid_provider_error_code"
    observation = _blocked_observation(definition, request, code, f"selected-case {code}", evidence_refs, runner=runner)
    return evaluate_scenario_set_v2(definition.scenario_set, (observation,), scorer=definition.scorer)


def _request_matches_snapshot(request: ProviderExecutionRequest, snapshot: dict[str, object]) -> bool:
    try:
        return request.model_dump(mode="json") == snapshot
    except (TypeError, ValueError, PydanticSerializationError):
        return False


async def _judge_bindings(judge: SelectedCaseJudgeAdapter | None) -> _JudgeBindings | None:
    if judge is None:
        return None

    async def read_bindings() -> _JudgeBindings | None:
        raw_identity, raw_judge, raw_cleanup = judge.identity, judge.judge, judge.cleanup
        if not isinstance(raw_identity, ProviderIdentityV2):
            return None
        identity = ProviderIdentityV2.model_validate(raw_identity.model_dump(mode="json"))
        if not inspect.iscoroutinefunction(raw_judge) or not inspect.iscoroutinefunction(raw_cleanup):
            return None
        inspect.signature(raw_judge).bind(None)
        inspect.signature(raw_cleanup).bind()
        fields = (
            identity.provider_id,
            identity.model_id,
            identity.version_or_digest,
            identity.adapter_id,
            identity.adapter_version_or_digest,
        )
        if not all(_public_text_is_redaction_safe(value) for value in fields):
            return None
        return _JudgeBindings(
            identity=identity,
            judge=cast(Callable[[SelectedCaseJudgeInput], Awaitable[object]], raw_judge),
            cleanup=cast(Callable[[], Awaitable[None]], raw_cleanup),
        )

    observed = (await gather(read_bindings(), return_exceptions=True))[0]
    if isinstance(observed, BaseException):
        return None
    return observed


def _consume_detached_judge_result(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except CancelledError:
        return


async def _bounded_judge_wait(awaitable: Awaitable[object], seconds: float) -> object:
    """Return at the deadline even when a host hook ignores cancellation."""
    waiter = asyncio.create_task(DEFAULT_PROVIDER_CALL_CLOCK.wait_for(awaitable, seconds))
    try:
        done, _pending = await asyncio.wait({waiter}, timeout=seconds)
        if waiter in done:
            return waiter.result()
        waiter.cancel()
        waiter.add_done_callback(_consume_detached_judge_result)
        raise TimeoutError
    except CancelledError:
        waiter.cancel()
        waiter.add_done_callback(_consume_detached_judge_result)
        raise


async def _judge_once(
    judge: _JudgeBindings,
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    output_text: str,
    output_sha256: str,
    limits: ProviderCallLimits,
) -> tuple[object | None, str | None]:
    evidence: object | None = None
    failure: str | None = None
    inputs = SelectedCaseJudgeInput(
        request=request,
        output_text=output_text,
        output_sha256=output_sha256,
        assertion_contract_sha256=definition.assertion_contract_sha256,
        assertions=definition.semantic_assertions,
    )

    async def invoke_judge() -> object:
        return await judge.judge(inputs)

    async def invoke_cleanup() -> None:
        return await judge.cleanup()

    try:
        observed = (
            await gather(
                _bounded_judge_wait(invoke_judge(), limits.overall_seconds),
                return_exceptions=True,
            )
        )[0]
        if isinstance(observed, CancelledError):
            failure = "judge_execution_failed"
        elif isinstance(observed, TimeoutError):
            failure = "judge_timeout"
        elif isinstance(observed, BaseException):
            failure = "judge_execution_failed"
        else:
            evidence = observed
    finally:
        cleanup_result = (
            await gather(
                _bounded_judge_wait(invoke_cleanup(), limits.cleanup_seconds),
                return_exceptions=True,
            )
        )[0]
        if failure is None and isinstance(cleanup_result, CancelledError):
            failure = "judge_cleanup_failed"
        elif failure is None and isinstance(cleanup_result, TimeoutError):
            failure = "judge_cleanup_timeout"
        elif failure is None and (isinstance(cleanup_result, BaseException) or cleanup_result is not None):
            failure = "judge_cleanup_failed"
    return evidence, failure


async def _convert_judge_evidence(value: object) -> SelectedCaseJudgeEvidence:
    return _validated_judge_artifact(value)


async def execute_selected_case_with_judge(
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    input_payload: JsonValue | SelectedCaseExecutionInput,
    adapter: TextProviderAdapter | None,
    judge: SelectedCaseJudgeAdapter | None,
) -> EvaluationReceiptV2:
    """Execute one provider call, then judge its actual output before scoring."""

    safety_evidence = None
    if isinstance(input_payload, SelectedCaseExecutionInput):
        safety_evidence = input_payload.safety_evidence
        input_payload = input_payload.payload

    async def revalidate_definition() -> SelectedCaseDefinition:
        return _revalidate_definition(definition)

    observed_definition = (await gather(revalidate_definition(), return_exceptions=True))[0]
    if isinstance(observed_definition, BaseException):
        raise ContractError(
            "invalid_selected_case_definition", "selected-case definition failed revalidation"
        ) from None
    definition = observed_definition

    async def revalidate_request() -> ProviderExecutionRequest:
        return ProviderExecutionRequest.model_validate(request)

    observed_request = (await gather(revalidate_request(), return_exceptions=True))[0]
    if isinstance(observed_request, BaseException):
        raise ContractError("invalid_provider_request", "provider request failed revalidation") from None
    request = observed_request
    provider_fields = (
        request.provider.provider_id,
        request.provider.model_id,
        request.provider.version_or_digest,
        request.provider.adapter_id,
        request.provider.adapter_version_or_digest,
    )
    if not all(_public_text_is_redaction_safe(value) for value in provider_fields):
        raise ContractError("invalid_provider_request", "provider identity contains private values")
    payload = _canonical_input_payload(input_payload)
    if not _request_matches_definition(definition, request, payload):
        return _blocked(definition, request, "selected_case_request_mismatch")
    if request.status != "prepared":
        blocker = request.blocker
        return _blocked(
            definition,
            request,
            blocker.code if blocker is not None else "provider_request_blocked",
            blocker.evidence_refs if blocker is not None else request.evidence_refs,
        )
    safety_blocker = assess_pre_execution_safety(request, safety_evidence, package_root=definition._package_root)
    if safety_blocker is not None:
        return _blocked(definition, request, safety_blocker.code, safety_blocker.evidence_refs)
    if adapter is None:
        return _blocked(definition, request, "provider_adapter_required")
    judge_bindings = await _judge_bindings(judge)
    if judge_bindings is None:
        return _blocked(definition, request, "judge_adapter_required")
    try:
        judge_limits = replace(DEFAULT_PROVIDER_CALL_LIMITS)
    except (AttributeError, TypeError, ValueError):
        return _blocked(definition, request, "invalid_judge_limits")
    request_payload = request.model_dump(mode="json")
    stable_request = ProviderExecutionRequest.model_validate(request_payload)
    try:
        outcome = await execute_provider_call(request, payload, adapter)
    except ContractError as exc:
        return _blocked(definition, stable_request, exc.code)
    if not _request_matches_snapshot(request, request_payload):
        return _blocked(definition, stable_request, "selected_case_request_mutated")
    try:
        outcome.public_result.execution.validate_against_request(stable_request)
    except ValueError:
        return _blocked(
            definition, stable_request, "selected_case_request_mutated", outcome.public_result.execution.evidence_refs
        )
    failure = outcome.public_result.execution.blocker or outcome.public_result.execution.error
    if not outcome.public_result.cleanup_succeeded:
        if failure is not None:
            return _blocked(definition, stable_request, failure.code, failure.evidence_refs)
        return _blocked(
            definition, stable_request, "provider_cleanup_failed", outcome.public_result.execution.evidence_refs
        )
    output = outcome.complete_text
    digest = outcome.public_result.output_sha256
    if output is None or digest is None:
        return _blocked(
            definition,
            stable_request,
            failure.code if failure is not None else "provider_output_unavailable",
            failure.evidence_refs if failure is not None else (),
        )
    if hashlib.sha256(output.encode("utf-8")).hexdigest() != digest:
        return _blocked(definition, stable_request, "invalid_provider_output")
    refs = outcome.public_result.execution.evidence_refs
    if any(not _public_text_is_redaction_safe(ref) for ref in refs):
        return _blocked(definition, stable_request, "private_provider_evidence_ref")
    judge_request = ProviderExecutionRequest.model_validate(request_payload)
    raw_evidence, failure = await _judge_once(judge_bindings, definition, judge_request, output, digest, judge_limits)
    if not _request_matches_snapshot(request, request_payload) or not _request_matches_snapshot(
        judge_request, request_payload
    ):
        return _blocked(
            definition, stable_request, "selected_case_request_mutated", refs, runner=judge_bindings.identity
        )
    if failure is not None:
        return _blocked(definition, stable_request, failure, refs, runner=judge_bindings.identity)
    converted = (await gather(_convert_judge_evidence(raw_evidence), return_exceptions=True))[0]
    if isinstance(converted, BaseException):
        return _blocked(definition, stable_request, "invalid_judge_evidence", refs, runner=judge_bindings.identity)
    evidence = converted
    if evidence.judge != judge_bindings.identity:
        return _blocked(definition, stable_request, "judge_identity_mismatch", refs, runner=judge_bindings.identity)
    observation = _validated_observation(definition, stable_request, evidence, output, digest, refs)
    return evaluate_scenario_set_v2(definition.scenario_set, (observation,), scorer=definition.scorer)


__all__ = ["SelectedCaseJudgeAdapter", "SelectedCaseJudgeInput", "execute_selected_case_with_judge"]
