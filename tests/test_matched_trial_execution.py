"""Independent trial requests and the actual descriptor-selected adapter route."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import get_type_hints

import pytest
from pydantic import ValidationError
from test_matched_execution import _matched

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import (
    DimensionalJudgeAdapter,
    MatchedCompleteProviderAdapter,
    MatchedProviderAdapter,
    MatchedStreamingProviderAdapter,
    MatchedTrialAdapters,
    MatchedVariantExecution,
    execute_matched_lane,
)
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.models.matched_execution import MatchedExecutionReceipt
from skills_sdk.models.matched_trial import matched_trial_identity
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.providers import ProviderAdapterChunk, ProviderAdapterComplete, ProviderAdapterTerminal


class RecordingProvider:
    """Simulate an idempotent host without counting cached requests as fresh work."""

    def __init__(self, delegate: object, requests: list[object], cache: dict[str, object]) -> None:
        self.delegate, self.requests, self.cache = delegate, requests, cache
        self.descriptor, self.parameters = delegate.descriptor, delegate.parameters

    async def complete(self, request: ProviderExecutionRequest, input_payload: object) -> ProviderAdapterComplete:
        self.requests.append(request)
        if request.idempotency_key_sha256 not in self.cache:
            self.cache[request.idempotency_key_sha256] = await self.delegate.complete(request, input_payload)
        return self.cache[request.idempotency_key_sha256]

    async def cleanup(self) -> None:
        await self.delegate.cleanup()


@pytest.fixture(scope="module")
def observed_trials(tmp_path_factory: pytest.TempPathFactory) -> tuple[object, ...]:
    plan, calibrations, batch, events = _matched(tmp_path_factory.mktemp("matched-trials"), trials=2)
    requests: list[object] = []
    cache: dict[str, object] = {}

    def recording(item: MatchedVariantExecution) -> MatchedVariantExecution:
        return replace(
            item,
            provider=RecordingProvider(item.provider, requests, cache),
            additional_trials=tuple(
                MatchedTrialAdapters(RecordingProvider(adapters.provider, requests, cache), adapters.judge)
                for adapters in item.additional_trials
            ),
        )

    observed = tuple(
        replace(
            pair,
            **{
                variant: recording(item)
                for variant, item in (("baseline", pair.baseline), ("candidate", pair.candidate))
            },
        )
        for pair in batch
    )
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, observed))
    assert receipt.status == "completed"
    return receipt, requests, cache, events


def test_trials_dispatch_and_retain_distinct_deterministic_requests(observed_trials: tuple[object, ...]) -> None:
    receipt, requests, cache, events = observed_trials
    retained = [request for pair in receipt.pairs for request in (pair.baseline_request, pair.candidate_request)]
    assert retained == requests
    assert len({request.request_id for request in requests}) == len(cache) == 40
    assert events.count("provider") == receipt.provider_invocation_count == 40
    assert len({pair.case_id for pair in receipt.pairs}) == 10
    for pair in receipt.pairs:
        for variant in ("baseline", "candidate"):
            request = getattr(pair, f"{variant}_request")
            assert (request.request_id, request.idempotency_key_sha256) == matched_trial_identity(
                receipt.plan.digest, receipt.lane, pair.case_id, variant, pair.trial_index
            )
    assert MatchedExecutionReceipt.model_validate_json(receipt.model_dump_json()) == receipt


@pytest.mark.parametrize(
    "mutation", ["request_id", "idempotency", "trial", "variant", "input", "case", "candidate", "capability"]
)
def test_forged_retained_trial_request_rejected_then_recovers(
    observed_trials: tuple[object, ...], mutation: str
) -> None:
    receipt = observed_trials[0]
    raw = receipt.model_dump(mode="json")
    target = raw["pairs"][0]["baseline_request"]
    if mutation == "request_id":
        target["request_id"] = "reused-request"
    elif mutation == "idempotency":
        target["idempotency_key_sha256"] = "0" * 64
    elif mutation == "trial":
        raw["pairs"][0]["baseline_request"] = raw["pairs"][1]["baseline_request"]
    elif mutation == "variant":
        raw["pairs"][0]["baseline_request"] = raw["pairs"][0]["candidate_request"]
    elif mutation == "input":
        target["input_sha256"] = "0" * 64
    elif mutation == "case":
        target["case_id"] = "other-case"
    elif mutation == "capability":
        target["declared_capability"] = "embedding"
    else:
        target["candidate"]["source_revision"] = "other-revision"
    with pytest.raises(ValidationError):
        MatchedExecutionReceipt.model_validate(raw)
    with pytest.raises(ContractError, match=r"^contract_validation_failed:"):
        SchemaRegistry().validate("matched-execution.v1", raw)
    forged = receipt.model_copy(update={"pairs": tuple(raw["pairs"])})
    with pytest.raises(ValidationError):
        MatchedExecutionReceipt.model_validate(forged)
    assert MatchedExecutionReceipt.model_validate(receipt) == receipt
    SchemaRegistry().validate("matched-execution.v1", receipt.model_dump(mode="json"))


class StreamingProvider:
    """Implement only the public stream-mode matched protocol, with explicit close proof."""

    def __init__(self, delegate: object, *, change_source: Path | None = None) -> None:
        self.descriptor = delegate.descriptor.model_copy(update={"mode": "stream"})
        self.parameters = delegate.parameters
        self.events = delegate.events
        self.change_source = change_source

    async def stream(
        self, request: ProviderExecutionRequest, input_payload: object
    ) -> AsyncIterator[ProviderAdapterChunk | ProviderAdapterTerminal]:
        del request, input_payload
        self.events.append("stream_open")

        async def output() -> AsyncIterator[ProviderAdapterChunk | ProviderAdapterTerminal]:
            try:
                self.events.append("stream_pull")
                if self.change_source is not None:
                    self.change_source.write_text("Changed during a pull.\n")
                yield ProviderAdapterChunk("behavior preserved")
                self.events.append("stream_pull")
                yield ProviderAdapterTerminal(evidence_refs=("evidence/stream.json",))
            finally:
                self.events.append("stream_closed")

        return output()

    async def cleanup(self) -> None:
        self.events.append("stream_cleanup")


def _stream_plan(plan: MatchedComparisonPlan) -> MatchedComparisonPlan:
    """Explicitly freeze local pull streaming without changing cloud controls."""
    raw = plan.model_dump(mode="json")
    raw["lanes"][0]["generator_mode"] = "stream"
    return MatchedComparisonPlan.model_validate(raw)


def test_public_matched_protocols_describe_required_parameters_and_dimensional_judge() -> None:
    hints = get_type_hints(MatchedVariantExecution)
    assert hints["provider"] == MatchedProviderAdapter
    assert hints["judge"] is DimensionalJudgeAdapter
    for protocol in (MatchedCompleteProviderAdapter, MatchedStreamingProviderAdapter):
        assert "parameters" in get_type_hints(protocol)


def test_stream_only_adapters_execute_all_trials_and_close_each_iterator(tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)

    def streaming_trials(item: MatchedVariantExecution) -> MatchedVariantExecution:
        return replace(
            item,
            provider=StreamingProvider(item.provider),
            additional_trials=tuple(
                MatchedTrialAdapters(StreamingProvider(adapters.provider), adapters.judge)
                for adapters in item.additional_trials
            ),
        )

    streaming = tuple(
        replace(
            pair,
            **{
                variant: streaming_trials(item)
                for variant, item in (("baseline", pair.baseline), ("candidate", pair.candidate))
            },
        )
        for pair in batch
    )
    receipt = asyncio.run(execute_matched_lane(_stream_plan(plan), "local", calibrations, streaming))
    assert receipt.status == "completed"
    assert receipt.provider_invocation_count == receipt.judge_invocation_count == 40
    assert events.count("stream_open") == events.count("stream_closed") == events.count("stream_cleanup") == 40
    assert events.count("stream_pull") == 80
    assert "provider" not in events


def test_source_mutation_during_stream_blocks_before_judge_and_recovers(tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)
    source = batch[0].baseline.plugin_context.root / "shared.md"
    original = source.read_bytes()
    broken = replace(batch[0].baseline, provider=StreamingProvider(batch[0].baseline.provider, change_source=source))
    modified = (replace(batch[0], baseline=broken), *batch[1:])
    blocked = asyncio.run(execute_matched_lane(_stream_plan(plan), "local", calibrations, modified))
    assert blocked.status == "blocked" and blocked.blocker.code == "matched_plugin_source_changed"
    assert blocked.provider_invocation_count == 1 and blocked.judge_invocation_count == 0
    assert events == ["stream_open", "stream_pull", "stream_closed", "stream_cleanup"]
    source.write_bytes(original)
    events.clear()
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


@pytest.mark.parametrize("drift", ["parameters", "descriptor"])
def test_stream_open_settings_drift_blocks_before_first_pull_and_recovers(tmp_path: Path, drift: str) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)

    class DriftingStream(StreamingProvider):
        async def stream(
            self, request: ProviderExecutionRequest, input_payload: object
        ) -> AsyncIterator[ProviderAdapterChunk | ProviderAdapterTerminal]:
            iterator = await super().stream(request, input_payload)
            if drift == "parameters":
                self.parameters = self.parameters.model_copy(update={"trial_count": 3})
            else:
                self.descriptor = self.descriptor.model_copy(update={"mode": "complete"})
            return iterator

    broken = replace(batch[0].baseline, provider=DriftingStream(batch[0].baseline.provider))
    modified = (replace(batch[0], baseline=broken), *batch[1:])
    blocked = asyncio.run(execute_matched_lane(_stream_plan(plan), "local", calibrations, modified))
    assert blocked.status == "blocked" and blocked.blocker.code == "matched_execution_incomplete"
    assert blocked.provider_invocation_count == 1 and blocked.judge_invocation_count == 0
    assert events == ["stream_open", "stream_cleanup"]
    events.clear()
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"
