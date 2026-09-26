"""Run one selected case through injected provider and semantic-judge adapters."""

from __future__ import annotations

import hashlib
import inspect
from asyncio import CancelledError, gather
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.deterministic_v2 import evaluate_scenario_set_v2
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
from skills_sdk.providers import (
    DEFAULT_PROVIDER_CALL_CLOCK,
    DEFAULT_PROVIDER_CALL_LIMITS,
    JsonValue,
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


def _blocked(definition: SelectedCaseDefinition, request: ProviderExecutionRequest, code: str) -> EvaluationReceiptV2:
    observation = _blocked_observation(definition, request, code, f"selected-case {code}")
    return evaluate_scenario_set_v2(definition.scenario_set, (observation,), scorer=definition.scorer)


def _judge_identity(judge: SelectedCaseJudgeAdapter | None) -> ProviderIdentityV2 | None:
    if judge is None:
        return None
    try:
        identity = ProviderIdentityV2.model_validate(judge.identity.model_dump(mode="json"))
        if not inspect.iscoroutinefunction(judge.judge) or not inspect.iscoroutinefunction(judge.cleanup):
            return None
        fields = (
            identity.provider_id,
            identity.model_id,
            identity.version_or_digest,
            identity.adapter_id,
            identity.adapter_version_or_digest,
        )
        return identity if all(_public_text_is_redaction_safe(value) for value in fields) else None
    except (AttributeError, TypeError, ValueError, ValidationError, PydanticSerializationError):
        return None


async def _judge_once(
    judge: SelectedCaseJudgeAdapter,
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    output_text: str,
    output_sha256: str,
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
    try:
        observed = (
            await gather(
                DEFAULT_PROVIDER_CALL_CLOCK.wait_for(judge.judge(inputs), DEFAULT_PROVIDER_CALL_LIMITS.overall_seconds),
                return_exceptions=True,
            )
        )[0]
        if isinstance(observed, CancelledError):
            raise observed
        if isinstance(observed, TimeoutError):
            failure = "judge_timeout"
        elif isinstance(observed, BaseException):
            failure = "judge_execution_failed"
        else:
            evidence = observed
    finally:
        cleanup_result = (
            await gather(
                DEFAULT_PROVIDER_CALL_CLOCK.wait_for(judge.cleanup(), DEFAULT_PROVIDER_CALL_LIMITS.cleanup_seconds),
                return_exceptions=True,
            )
        )[0]
        if isinstance(cleanup_result, CancelledError):
            raise cleanup_result
        if isinstance(cleanup_result, TimeoutError):
            failure = "judge_cleanup_timeout"
        elif isinstance(cleanup_result, BaseException) or cleanup_result is not None:
            failure = "judge_cleanup_failed"
    return evidence, failure


async def execute_selected_case_with_judge(
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    input_payload: JsonValue,
    adapter: TextProviderAdapter | None,
    judge: SelectedCaseJudgeAdapter | None,
) -> EvaluationReceiptV2:
    """Execute one provider call, then judge its actual output before scoring."""
    definition = _revalidate_definition(definition)
    try:
        request = ProviderExecutionRequest.model_validate(request)
    except ValidationError:
        raise ContractError("invalid_provider_request", "provider request failed revalidation") from None
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
        return _blocked(definition, request, "provider_request_blocked")
    if adapter is None:
        return _blocked(definition, request, "provider_adapter_required")
    judge_identity = _judge_identity(judge)
    if judge_identity is None or judge is None:
        return _blocked(definition, request, "judge_adapter_required")
    try:
        outcome = await execute_provider_call(request, payload, adapter)
    except ContractError as exc:
        return _blocked(definition, request, exc.code)
    if not outcome.public_result.cleanup_succeeded:
        return _blocked(definition, request, "provider_cleanup_failed")
    output = outcome.complete_text
    digest = outcome.public_result.output_sha256
    if output is None or digest is None:
        failure = outcome.public_result.execution.blocker or outcome.public_result.execution.error
        return _blocked(definition, request, failure.code if failure is not None else "provider_output_unavailable")
    if hashlib.sha256(output.encode("utf-8")).hexdigest() != digest:
        return _blocked(definition, request, "invalid_provider_output")
    refs = outcome.public_result.execution.evidence_refs
    if any(not _public_text_is_redaction_safe(ref) for ref in refs):
        return _blocked(definition, request, "private_provider_evidence_ref")
    raw_evidence, failure = await _judge_once(judge, definition, request, output, digest)
    if failure is not None:
        return _blocked(definition, request, failure)
    try:
        evidence = _validated_judge_artifact(raw_evidence)
    except (AttributeError, TypeError, ValueError, ValidationError, PydanticSerializationError):
        return _blocked(definition, request, "invalid_judge_evidence")
    if evidence.judge != judge_identity:
        return _blocked(definition, request, "judge_identity_mismatch")
    observation = _validated_observation(definition, request, evidence, output, digest, refs)
    return evaluate_scenario_set_v2(definition.scenario_set, (observation,), scorer=definition.scorer)


__all__ = ["SelectedCaseJudgeAdapter", "SelectedCaseJudgeInput", "execute_selected_case_with_judge"]
