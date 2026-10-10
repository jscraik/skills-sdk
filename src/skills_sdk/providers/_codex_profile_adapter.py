"""Offline adapters that supply compiled profile settings with drift guards."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol

from skills_sdk.core.errors import ContractError
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.models.matched_ingress import _canonical_matched_input
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.scorer_quality import ScorerJudgeParameters
from skills_sdk.providers._codex_profile_binding import _CodexProfileSource
from skills_sdk.providers._codex_profile_invocation import _CodexProfileInvocation, _compile_codex_profile
from skills_sdk.providers.types import JsonValue, ProviderAdapterComplete, ProviderAdapterStreamItem


class _ProfiledDriver(Protocol):
    async def cleanup(self) -> None: ...


class _ProfiledCompleteDriver(_ProfiledDriver, Protocol):
    async def complete(
        self, invocation: _CodexProfileInvocation, request: ProviderExecutionRequest, payload: JsonValue
    ) -> ProviderAdapterComplete: ...


class _ProfiledStreamingDriver(_ProfiledDriver, Protocol):
    async def stream(
        self, invocation: _CodexProfileInvocation, request: ProviderExecutionRequest, payload: JsonValue
    ) -> AsyncIterator[ProviderAdapterStreamItem]: ...


class _ProfiledJudgeDriver(_ProfiledDriver, Protocol):
    async def judge(self, invocation: _CodexProfileInvocation, inputs: object) -> object: ...


class _CodexProfiledAdapterBase:
    """Apply an explicit invocation to an injected driver, with drift checks.

    This implements the existing offline adapter contract, not a live Codex client.
    The surrounding SDK execution route owns source safety, budgets and cleanup.
    """

    _mode: Literal["complete", "stream"] = "complete"
    _role: Literal["generator", "judge"] = "generator"

    def __init__(self, plan: object, source: _CodexProfileSource, driver: _ProfiledDriver) -> None:
        self.plan = MatchedComparisonPlan.model_validate(plan)
        self.source, self.driver = source, driver
        self._invocation = _compile_codex_profile(self.plan, source, self._role)
        self._lane = self.plan.lanes[0 if source.name == "oss-local.config.toml" else 1]
        self._stream_iterator: AsyncIterator[ProviderAdapterStreamItem] | None = None
        if self._role == "generator" and self._lane.generator_mode != self._mode:
            raise ContractError("model_profile_mode_unsupported", "adapter mode must match the frozen lane")

    def _check(self) -> _CodexProfileInvocation:
        try:
            current = _compile_codex_profile(self.plan, self.source, self._role)
        except ContractError:
            raise ContractError(
                "model_profile_binding_changed", "rebind changed profile inputs before execution"
            ) from None
        if current != self._invocation:
            raise ContractError("model_profile_binding_changed", "rebind changed profile inputs before execution")
        return current

    @property
    def descriptor(self) -> TextProviderAdapterDescriptor:
        self._check()
        if self._role != "generator":
            raise ContractError("model_profile_role_mismatch", "a judge is not a generation adapter")
        return TextProviderAdapterDescriptor(provider=self._lane.generator, mode=self._mode)

    @property
    def parameters(self) -> ScorerJudgeParameters:
        self._check()
        return self._lane.generator_parameters if self._role == "generator" else self._lane.judge_parameters

    def _request(self, request: ProviderExecutionRequest) -> ProviderExecutionRequest:
        current_request = ProviderExecutionRequest.model_validate(_canonical_matched_input(request))
        if current_request.provider != self.descriptor.provider or current_request.status != "prepared":
            raise ContractError("model_profile_request_mismatch", "request must bind the selected prepared model")
        return current_request

    async def cleanup(self) -> None:
        try:
            iterator, self._stream_iterator = self._stream_iterator, None
            close = getattr(iterator, "aclose", None)
            if callable(close):
                await close()
        finally:
            if await self.driver.cleanup() is not None:
                raise ContractError("model_profile_cleanup_invalid", "profile driver cleanup must return None")


class _CodexProfiledCompleteAdapter(_CodexProfiledAdapterBase):
    async def complete(self, request: ProviderExecutionRequest, input_payload: JsonValue) -> ProviderAdapterComplete:
        invocation = self._check()
        current_request = self._request(request)
        callback = self.driver.complete
        self._check()
        result = await callback(invocation, current_request, input_payload)
        self._check()
        return result


class _CodexProfiledStreamingAdapter(_CodexProfiledAdapterBase):
    _mode: Literal["complete", "stream"] = "stream"

    async def stream(
        self, request: ProviderExecutionRequest, input_payload: JsonValue
    ) -> AsyncIterator[ProviderAdapterStreamItem]:
        invocation = self._check()
        current_request = self._request(request)
        callback = self.driver.stream
        self._check()
        iterator = await callback(invocation, current_request, input_payload)
        self._stream_iterator = iterator
        self._check()

        async def guarded() -> AsyncIterator[ProviderAdapterStreamItem]:
            while True:
                self._check()
                try:
                    value = await anext(iterator)
                except StopAsyncIteration:
                    self._check()
                    return
                self._check()
                yield value

        return guarded()


class _CodexProfiledJudgeAdapter(_CodexProfiledAdapterBase):
    """Pass judge-specific settings without changing dimensional verdict validation."""

    _role: Literal["generator", "judge"] = "judge"

    @property
    def identity(self) -> ProviderIdentityV2:
        self._check()
        return self._lane.judge

    async def judge(self, inputs: object) -> object:
        invocation = self._check()
        callback = self.driver.judge
        self._check()
        result = await callback(invocation, inputs)
        self._check()
        return result
