"""Provider-then-judge selected-case orchestration regressions."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Coroutine
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from test_selected_case_evaluation import REVISION, _prepared_request, _skill

import skills_sdk.evaluation.live_selected_case as live_selected_case
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation import (
    SelectedCaseDefinition,
    SelectedCaseJudgeAdapter,
    SelectedCaseJudgeInput,
    execute_selected_case_with_judge,
    load_selected_case,
)
from skills_sdk.models.evaluation_v2 import EvaluationReceiptV2
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionBlocker, ProviderExecutionRequest
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


def test_blocked_request_preserves_original_reason_and_refs(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    blocked_request = request.model_copy(
        update={
            "status": "blocked",
            "blocker": ProviderExecutionBlocker(
                code="safety_unavailable", category="safety", evidence_refs=("safety/decision.json",)
            ),
        }
    )
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition,
            blocked_request,
            payload,
            _Provider(request, events),
            _Judge(request.provider, events),
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "safety_unavailable"
    assert receipt.case_results[0].blocker.evidence_refs == ("safety/decision.json",)
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


def test_first_judge_failure_survives_cleanup_failure(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _DoubleFailureJudge(_Judge):
        async def cleanup(self) -> None:
            self.events.append("judge_cleanup")
            raise RuntimeError("private cleanup failure")

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition,
            request,
            payload,
            _Provider(request, events),
            _DoubleFailureJudge(request.provider, events, failure=True),
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "judge_execution_failed"
    assert events == ["provider", "provider_cleanup", "judge", "judge_cleanup"]


@pytest.mark.parametrize("invalid_hook", ["judge", "cleanup"])
def test_invalid_judge_signature_blocks_before_provider(tmp_path: Path, invalid_hook: str) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _WrongJudgeSignature:
        identity = request.provider

        async def judge(self) -> object:
            raise AssertionError("must not be called")

        async def cleanup(self) -> None:
            raise AssertionError("must not be called")

    class _WrongCleanupSignature:
        identity = request.provider

        async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
            raise AssertionError("must not be called")

        async def cleanup(self, state: object) -> None:
            raise AssertionError("must not be called")

    judge = cast(
        SelectedCaseJudgeAdapter,
        _WrongJudgeSignature() if invalid_hook == "judge" else _WrongCleanupSignature(),
    )
    receipt = asyncio.run(
        execute_selected_case_with_judge(definition, request, payload, _Provider(request, events), judge)
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "judge_adapter_required"
    assert events == []


@pytest.mark.parametrize("unavailable_member", ["identity", "judge", "cleanup"])
@pytest.mark.parametrize("failure_type", [RuntimeError, OSError, KeyError])
def test_judge_capability_access_failure_blocks_before_provider(
    tmp_path: Path, unavailable_member: str, failure_type: type[Exception]
) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _UnavailableJudge:
        def __getattribute__(self, name: str) -> object:
            if name == unavailable_member:
                raise failure_type("private unavailable configuration")
            return object.__getattribute__(self, name)

        identity = request.provider

        async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
            raise AssertionError("must not be called")

        async def cleanup(self) -> None:
            raise AssertionError("must not be called")

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition,
            request,
            payload,
            _Provider(request, events),
            cast(SelectedCaseJudgeAdapter, _UnavailableJudge()),
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "judge_adapter_required"
    assert events == []


@pytest.mark.parametrize("unavailable_member", ["identity", "judge", "cleanup"])
def test_judge_binding_origin_cancellation_blocks_before_provider(tmp_path: Path, unavailable_member: str) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _CancelledBindingJudge(_Judge):
        def __getattribute__(self, name: str) -> object:
            if name == unavailable_member:
                raise asyncio.CancelledError
            return object.__getattribute__(self, name)

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition,
            request,
            payload,
            _Provider(request, events),
            _CancelledBindingJudge(request.provider, events),
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "judge_adapter_required"
    assert events == []


@pytest.mark.parametrize("stateful_hook", ["judge", "cleanup"])
def test_judge_hooks_are_bound_once_before_provider(tmp_path: Path, stateful_hook: str) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _SingleReadJudge(_Judge):
        reads = 0

        def __getattribute__(self, name: str) -> object:
            if name == stateful_hook:
                reads = object.__getattribute__(self, "reads") + 1
                object.__setattr__(self, "reads", reads)
                if reads > 1:
                    raise RuntimeError("host hook changed after preflight")
            return object.__getattribute__(self, name)

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _SingleReadJudge(request.provider, events)
        )
    )
    assert receipt.status == "pass"
    assert events == ["provider", "provider_cleanup", "judge", "judge_cleanup"]


def test_forged_judge_limits_block_before_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    definition, payload, request, events = _setup(tmp_path)
    forged = replace(live_selected_case.DEFAULT_PROVIDER_CALL_LIMITS)
    object.__setattr__(forged, "overall_seconds", 3600.0)
    monkeypatch.setattr(live_selected_case, "DEFAULT_PROVIDER_CALL_LIMITS", forged)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "invalid_judge_limits"
    assert events == []


@pytest.mark.parametrize("forged_adapter_id", ["forged-adapter", object()])
def test_judge_cannot_mutate_receipt_request_identity(tmp_path: Path, forged_adapter_id: object) -> None:
    definition, payload, request, events = _setup(tmp_path)
    original_provider = request.provider.model_dump(mode="json")

    class _MutatingJudge(_Judge):
        async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
            object.__setattr__(inputs.request.provider, "adapter_id", forged_adapter_id)
            return await super().judge(inputs)

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _MutatingJudge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mutated"
    assert request.provider.model_dump(mode="json") == original_provider


def test_provider_cannot_mutate_receipt_request_identity(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _MutatingProvider(_Provider):
        async def complete(self, request: ProviderExecutionRequest, input_payload: object) -> ProviderAdapterComplete:
            self.events.append("provider")
            object.__setattr__(request.provider, "adapter_id", object())
            return ProviderAdapterComplete(text=self.text)

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _MutatingProvider(request, events), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "invalid_provider_result"
    assert events == ["provider", "provider_cleanup"]


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
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "rate_limited"
    assert receipt.case_results[0].blocker.evidence_refs == ("provider/rate-limit.json",)
    assert events == ["provider", "provider_cleanup"]


def test_provider_failure_survives_cleanup_failure(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _DoubleFailureProvider(_FailedProvider):
        async def cleanup(self) -> None:
            self.events.append("provider_cleanup")
            raise RuntimeError("private cleanup failure")

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _DoubleFailureProvider(request, events), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "rate_limited"
    assert receipt.case_results[0].blocker.evidence_refs == ("provider/rate-limit.json",)
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


def test_judge_evidence_serializer_failure_blocks_with_provider_provenance(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _BrokenEvidence(SelectedCaseJudgeEvidence):
        def model_dump(self, *args: object, **kwargs: object) -> dict[str, object]:
            raise OSError("private serializer failure")

    class _BrokenSerializerJudge(_Judge):
        async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
            evidence = cast(SelectedCaseJudgeEvidence, await super().judge(inputs))
            return _BrokenEvidence.model_construct(**evidence.model_dump(mode="python"))

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _BrokenSerializerJudge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "invalid_judge_evidence"
    assert "evidence/provider-result.json" in receipt.case_results[0].blocker.evidence_refs
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


@pytest.mark.parametrize("failed_hook", ["judge", "cleanup"])
def test_sync_awaitable_factory_failure_blocks_with_provider_provenance(tmp_path: Path, failed_hook: str) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _SyncFailureJudge(_Judge):
        @inspect.markcoroutinefunction
        def judge(self, inputs: SelectedCaseJudgeInput) -> Awaitable[object]:
            if failed_hook == "judge":
                self.events.append("judge")
                raise OSError("private judge setup failure")
            return super().judge(inputs)

        @inspect.markcoroutinefunction
        def cleanup(self) -> Awaitable[None]:
            if failed_hook == "cleanup":
                self.events.append("judge_cleanup")
                raise OSError("private cleanup setup failure")
            return super().cleanup()

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _SyncFailureJudge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    expected = "judge_execution_failed" if failed_hook == "judge" else "judge_cleanup_failed"
    assert receipt.case_results[0].blocker.code == expected
    assert "evidence/provider-result.json" in receipt.case_results[0].blocker.evidence_refs
    assert events == ["provider", "provider_cleanup", "judge", "judge_cleanup"]


@pytest.mark.parametrize("cancelled_hook", ["judge", "cleanup"])
def test_hook_origin_cancellation_is_a_typed_failure(tmp_path: Path, cancelled_hook: str) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _CancelledJudge(_Judge):
        async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
            if cancelled_hook == "judge":
                self.events.append("judge")
                raise asyncio.CancelledError
            return await super().judge(inputs)

        async def cleanup(self) -> None:
            self.events.append("judge_cleanup")
            if cancelled_hook == "cleanup":
                raise asyncio.CancelledError

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _CancelledJudge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    expected = "judge_execution_failed" if cancelled_hook == "judge" else "judge_cleanup_failed"
    assert receipt.case_results[0].blocker.code == expected
    assert "evidence/provider-result.json" in receipt.case_results[0].blocker.evidence_refs
    assert events == ["provider", "provider_cleanup", "judge", "judge_cleanup"]


def test_cleanup_origin_cancellation_does_not_hide_judge_failure(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _DoubleFailureJudge(_Judge):
        async def cleanup(self) -> None:
            self.events.append("judge_cleanup")
            raise asyncio.CancelledError

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition,
            request,
            payload,
            _Provider(request, events),
            _DoubleFailureJudge(request.provider, events, failure=True),
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "judge_execution_failed"


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


def test_judge_timeout_does_not_wait_for_uncooperative_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition, payload, request, events = _setup(tmp_path)
    release = asyncio.Event()
    cancelled = asyncio.Event()
    finished = asyncio.Event()
    monkeypatch.setattr(
        live_selected_case,
        "DEFAULT_PROVIDER_CALL_LIMITS",
        replace(live_selected_case.DEFAULT_PROVIDER_CALL_LIMITS, overall_seconds=0.01),
    )

    class _UncooperativeJudge(_Judge):
        async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
            self.events.append("judge")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                finished.set()
                return await super().judge(inputs)

    async def run() -> tuple[EvaluationReceiptV2, bool, bool]:
        task = asyncio.create_task(
            execute_selected_case_with_judge(
                definition, request, payload, _Provider(request, events), _UncooperativeJudge(request.provider, events)
            )
        )
        try:
            receipt = await asyncio.wait_for(task, timeout=0.5)
            return receipt, not finished.is_set(), "judge_cleanup" in events
        finally:
            release.set()
            await asyncio.sleep(0)

    receipt, hook_live_at_return, cleanup_started_while_live = asyncio.run(run())
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "judge_timeout"
    assert cancelled.is_set()
    assert hook_live_at_return
    assert cleanup_started_while_live
    assert events[:3] == ["provider", "provider_cleanup", "judge"]
    assert "judge_cleanup" in events


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
