"""Provider-then-judge selected-case orchestration regressions."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Coroutine
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from test_live_selected_case import (
    _BadEvidenceJudge,
    _CleanupFailedProvider,
    _CleanupValueJudge,
    _FailedProvider,
    _Judge,
    _Provider,
    _setup,
)
from test_selected_case_evaluation import REVISION, _safety_for, _skill

import skills_sdk.evaluation.live_selected_case as live_selected_case
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation import (
    SelectedCaseJudgeInput,
    execute_selected_case_with_judge,
    load_selected_case,
)
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.models.evaluation_v2 import EvaluationReceiptV2
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence


def test_provider_failure_never_invokes_judge(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _FailedProvider(request, events),
            _Judge(request.provider, events),
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
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _DoubleFailureProvider(request, events),
            _Judge(request.provider, events),
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
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _CleanupFailedProvider(request, events),
            _Judge(request.provider, events),
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "provider_cleanup_failed"
    assert "evidence/provider-result.json" in receipt.case_results[0].blocker.evidence_refs
    assert events == ["provider", "provider_cleanup"]


def test_judge_evidence_must_bind_actual_output(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events),
            _BadEvidenceJudge(request.provider, events),
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert "evidence/provider-result.json" in receipt.case_results[0].blocker.evidence_refs
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
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events),
            _BrokenSerializerJudge(request.provider, events),
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
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events),
            _MismatchedIdentityJudge(other, events),
        )
    )
    assert receipt.status == "blocked"


def test_judge_cleanup_must_resolve_to_none(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events),
            _CleanupValueJudge(request.provider, events),
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
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events),
            _CleanupFailedJudge(request.provider, events),
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
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events),
            _SyncFailureJudge(request.provider, events),
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
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events),
            _CancelledJudge(request.provider, events),
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
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
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
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events),
            _Judge(request.provider, events),
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
                definition,
                request,
                SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
                _Provider(request, events),
                _UncooperativeJudge(request.provider, events),
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
                definition,
                request,
                SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
                _Provider(request, events),
                _WaitingJudge(request.provider, events),
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
                definition,
                request,
                SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
                _Provider(request, events),
                _WaitingCleanupJudge(request.provider, events),
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
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events, text=malformed),
            _Judge(request.provider, events),
        )
    )
    assert receipt.status == "blocked"
    assert events == ["provider", "provider_cleanup"]
