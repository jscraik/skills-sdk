"""Provider-then-judge selected-case orchestration regressions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Coroutine
from pathlib import Path
from typing import cast

import pytest
from test_selected_case_evaluation import REVISION, _prepared_request, _skill

import skills_sdk.evaluation.live_selected_case as live_selected_case
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation import (
    SelectedCaseDefinition,
    SelectedCaseJudgeInput,
    execute_selected_case_with_judge,
    load_selected_case,
)
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence
from skills_sdk.providers import ProviderAdapterComplete, ProviderAdapterFailure


class _Provider:
    def __init__(self, request: ProviderExecutionRequest, events: list[str], text: str = "behavior preserved") -> None:
        self.descriptor = TextProviderAdapterDescriptor(provider=request.provider, mode="complete")
        self.events = events
        self.text = text

    async def complete(self, request: ProviderExecutionRequest, input_payload: object) -> ProviderAdapterComplete:
        del request, input_payload
        self.events.append("provider")
        return ProviderAdapterComplete(text=self.text, evidence_refs=("evidence/provider-result.json",))

    async def cleanup(self) -> None:
        self.events.append("provider_cleanup")


class _Judge:
    def __init__(self, identity: ProviderIdentityV2, events: list[str], *, failure: bool = False) -> None:
        self.identity = identity
        self.events = events
        self.failure = failure

    async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
        self.events.append("judge")
        assert inputs.output_text == "behavior preserved"
        assert len(inputs.assertions) == 2
        if self.failure:
            raise RuntimeError("private host failure")
        return SelectedCaseJudgeEvidence(
            candidate=inputs.request.candidate,
            scenario_set_id=inputs.request.scenario_set_id,
            case_id=inputs.request.case_id,
            provider=inputs.request.provider,
            assertion_contract_sha256=inputs.assertion_contract_sha256,
            judge=self.identity,
            satisfied_assertion_ids=tuple(item[0] for item in inputs.assertions),
            evidence_refs=("evidence/assertion-review.json", f"judge-results/{'c' * 64}"),
            output_sha256=inputs.output_sha256,
            judge_result_sha256="c" * 64,
        )

    async def cleanup(self) -> None:
        self.events.append("judge_cleanup")


def _setup(tmp_path: Path) -> tuple[SelectedCaseDefinition, dict[str, str], ProviderExecutionRequest, list[str]]:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    payload = {"prompt": definition.scenario_set.cases[0].prompt}
    return definition, payload, _prepared_request(definition, payload), []


def test_live_path_calls_provider_once_then_judge_actual_output(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "pass"
    assert events == ["provider", "provider_cleanup", "judge", "judge_cleanup"]


@pytest.mark.parametrize("missing", ["provider", "judge"])
def test_missing_capability_blocks_before_dispatch(tmp_path: Path, missing: str) -> None:
    definition, payload, request, events = _setup(tmp_path)
    provider = None if missing == "provider" else _Provider(request, events)
    judge = None if missing == "judge" else _Judge(request.provider, events)
    receipt = asyncio.run(execute_selected_case_with_judge(definition, request, payload, provider, judge))
    assert receipt.status == "blocked"
    assert events == []


def test_request_mismatch_blocks_before_dispatch(tmp_path: Path) -> None:
    definition, _payload, request, events = _setup(tmp_path)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, {"prompt": "other"}, _Provider(request, events), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert events == []


def test_forged_private_provider_identity_rejects_before_dispatch(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    provider = _Provider(request, events)
    judge = _Judge(request.provider, events)
    object.__setattr__(request.provider, "model_id", "sk-private")
    with pytest.raises(ContractError, match="invalid_provider_request"):
        asyncio.run(execute_selected_case_with_judge(definition, request, payload, provider, judge))
    assert events == []


def test_judge_failure_blocks_and_cleans_up(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _Judge(request.provider, events, failure=True)
        )
    )
    assert receipt.status == "blocked"
    assert events == ["provider", "provider_cleanup", "judge", "judge_cleanup"]


class _FailedProvider(_Provider):
    async def complete(self, request: ProviderExecutionRequest, input_payload: object) -> ProviderAdapterComplete:
        del request, input_payload
        self.events.append("provider")
        raise ProviderAdapterFailure(
            code="rate_limited", category="provider", retryable=True, evidence_refs=("provider/rate-limit.json",)
        )


class _CleanupFailedProvider(_Provider):
    async def cleanup(self) -> None:
        self.events.append("provider_cleanup")
        raise RuntimeError("private cleanup failure")


def test_provider_failure_never_invokes_judge(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _FailedProvider(request, events), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert events == ["provider", "provider_cleanup"]


def test_provider_cleanup_failure_never_invokes_judge(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _CleanupFailedProvider(request, events), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert events == ["provider", "provider_cleanup"]


class _BadEvidenceJudge(_Judge):
    async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
        evidence = cast(
            SelectedCaseJudgeEvidence,
            await super().judge(inputs),
        )
        return evidence.model_copy(update={"output_sha256": "a" * 64})


def test_judge_evidence_must_bind_actual_output(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _BadEvidenceJudge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert events == ["provider", "provider_cleanup", "judge", "judge_cleanup"]


def test_judge_identity_mismatch_blocks(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    other = request.provider.model_copy(update={"adapter_id": "other-adapter"})

    class _MismatchedIdentityJudge(_Judge):
        async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
            evidence = cast(SelectedCaseJudgeEvidence, await super().judge(inputs))
            return evidence.model_copy(update={"judge": request.provider})

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _MismatchedIdentityJudge(other, events)
        )
    )
    assert receipt.status == "blocked"


class _CleanupValueJudge(_Judge):
    async def cleanup(self) -> None:
        self.events.append("judge_cleanup")
        return cast(None, False)


def test_judge_cleanup_must_resolve_to_none(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _CleanupValueJudge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"


def test_judge_cleanup_failure_blocks(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _CleanupFailedJudge(_Judge):
        async def cleanup(self) -> None:
            self.events.append("judge_cleanup")
            raise RuntimeError("private cleanup failure")

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _CleanupFailedJudge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert events == ["provider", "provider_cleanup", "judge", "judge_cleanup"]


def test_judge_timeout_blocks_and_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _TimeoutClock:
        calls = 0

        async def wait_for(self, awaitable: Awaitable[object], timeout_seconds: float) -> object:
            del timeout_seconds
            self.calls += 1
            if self.calls == 1:
                cast(Coroutine[object, object, object], awaitable).close()
                raise TimeoutError
            return await awaitable

    monkeypatch.setattr(live_selected_case, "DEFAULT_PROVIDER_CALL_CLOCK", _TimeoutClock())
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert events == ["provider", "provider_cleanup", "judge_cleanup"]


def test_mode_mismatch_rejects_before_host_execution(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")
    with pytest.raises(ContractError, match="selected_case_mode_mismatch"):
        load_selected_case(package, source_revision=REVISION, case_id="edge-empty-diff", mode="smoke")


def test_cancelled_judge_still_cleans_up(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    entered = asyncio.Event()

    class _WaitingJudge(_Judge):
        async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
            del inputs
            self.events.append("judge")
            entered.set()
            await asyncio.Event().wait()
            return None

    async def run() -> None:
        task = asyncio.create_task(
            execute_selected_case_with_judge(
                definition, request, payload, _Provider(request, events), _WaitingJudge(request.provider, events)
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert events == ["provider", "provider_cleanup", "judge", "judge_cleanup"]


def test_cancellation_during_judge_cleanup_propagates(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    entered = asyncio.Event()

    class _WaitingCleanupJudge(_Judge):
        async def cleanup(self) -> None:
            self.events.append("judge_cleanup")
            entered.set()
            await asyncio.Event().wait()

    async def run() -> None:
        task = asyncio.create_task(
            execute_selected_case_with_judge(
                definition, request, payload, _Provider(request, events), _WaitingCleanupJudge(request.provider, events)
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert events == ["provider", "provider_cleanup", "judge", "judge_cleanup"]


def test_malformed_provider_output_never_invokes_judge(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    malformed = cast(str, {"wrong": "shape"})
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events, text=malformed), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert events == ["provider", "provider_cleanup"]
