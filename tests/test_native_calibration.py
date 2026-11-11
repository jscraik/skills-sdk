"""Native calibration uses real controlled subprocesses and unchanged safety gates."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_codex_judge import _events, _executable
from test_observed_calibration import NumericJudge, _batch

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import execute_native_calibration
from skills_sdk.evaluation.observed_calibration import execute_scorer_calibration
from skills_sdk.models.native_judge import CodexNativeJudgeParameters
from skills_sdk.models.observed_calibration import (
    NativeCalibrationPlan,
    NativeCalibrationReceipt,
    ObservedCalibrationPlan,
)
from skills_sdk.providers.codex_judge import CodexCalibrationJudgeAdapter, CodexJudgeAdapter, CodexJudgeSettings


async def _retain(ref: str, data: bytes) -> None:
    assert ref.startswith("judge-results/") and data


def _native_batch(root: Path) -> tuple[NativeCalibrationPlan, tuple, list[str]]:
    settings = CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ())
    executable = _executable(root, "print('unused')")
    identity = CodexJudgeAdapter(executable, root, settings, "Rubric", retain_result=_retain).identity
    original, executions, events = _batch(root, identity)
    raw = original.model_dump(mode="json", exclude={"schema_version"})
    raw["parameters"] = settings.calibration_parameters().model_dump(mode="json")
    raw["rubric_sha256"] = hashlib.sha256(b"Rubric").hexdigest()
    plan = NativeCalibrationPlan.model_validate(raw)
    controlled = []
    for index, (execution, score) in enumerate(zip(executions, (0.9, 0.1), strict=True)):
        folder = root / ("judge" + str(index))
        folder.mkdir()
        script = _executable(folder, "print(" + repr(_events(score, execution.definition.semantic_signal_ids)) + ")")
        judge = CodexCalibrationJudgeAdapter(
            CodexJudgeAdapter(script, folder, settings, "Rubric", retain_result=_retain)
        )
        controlled.append(replace(execution, judge=judge))
    return plan, tuple(controlled), events


def test_native_calibration_runs_guarded_subprocesses_without_temperature(tmp_path: Path) -> None:
    plan, executions, events = _native_batch(tmp_path)
    result = asyncio.run(execute_native_calibration(plan, executions))
    assert result.status == "pass" and result.judge_invocation_count == 2
    assert [row.score for row in result.results] == [0.9, 0.1]
    assert plan.parameters.temperature is None
    assert not result.external_authenticity_verified and not result.promotion_authorized
    assert events.count("provider") == 2
    SchemaRegistry().validate("native-calibration-plan.v1", plan.model_dump(mode="json"))
    SchemaRegistry().validate("native-calibration.v1", result.model_dump(mode="json"))
    assert NativeCalibrationReceipt.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError):
        ObservedCalibrationPlan.model_validate(plan.model_dump(mode="json"))


@pytest.mark.parametrize("change", [{"temperature": 0.0}, {"trial_count": True}, {"shell_tool": 0}, {"apps": True}])
def test_native_parameters_reject_invented_or_weakened_controls(tmp_path: Path, change: dict) -> None:
    plan, executions, events = _native_batch(tmp_path)
    raw = plan.model_dump(mode="json")
    raw["parameters"].update(change)
    with pytest.raises(ValidationError):
        NativeCalibrationPlan.model_validate(raw)
    result = asyncio.run(execute_native_calibration(raw, executions))
    assert result.blocker.code == "invalid_calibration_input"
    assert not result.judge_execution_performed and events == []


def test_native_settings_drift_and_reuse_block_before_judgment(tmp_path: Path) -> None:
    plan, executions, events = _native_batch(tmp_path)
    raw = plan.model_dump(mode="json")
    raw["parameters"]["reasoning_effort"] = "high"
    with pytest.raises(ValidationError):
        NativeCalibrationPlan.model_validate(raw)
    aliased = (executions[0], replace(executions[1], judge=executions[0].judge))
    result = asyncio.run(execute_native_calibration(plan, aliased))
    assert result.blocker.code == "calibration_capability_reuse" and events == []
    old = asyncio.run(execute_scorer_calibration(plan, executions))
    assert old.blocker.code == "invalid_calibration_input" and events == []


@pytest.mark.parametrize("drift_index", [0, 1])
@pytest.mark.parametrize("change", ["settings", "rubric"])
def test_native_batch_metadata_rejected_before_dispatch(tmp_path: Path, drift_index: int, change: str) -> None:
    """Reject every pre-existing judge mismatch without consuming an earlier probe."""
    plan, executions, events = _native_batch(tmp_path)
    folder = tmp_path / ("judge" + str(drift_index))
    settings = CodexJudgeSettings("gpt-6.1-sol", "0.153.4", (), timeout_seconds=60 if change == "settings" else 120)
    delegate = CodexJudgeAdapter(
        folder / "codex-fixture",
        folder,
        settings,
        "Changed rubric" if change == "rubric" else "Rubric",
        retain_result=_retain,
    )
    frames = tuple(
        replace(item, judge=CodexCalibrationJudgeAdapter(delegate)) if index == drift_index else item
        for index, item in enumerate(executions)
    )
    result = asyncio.run(execute_native_calibration(plan, frames))
    assert result.judge_invocation_count == 0 and events == []
    assert result.status == "blocked" and result.blocker.code == "invalid_calibration_input"
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


def test_native_batch_parameters_cannot_hide_behind_matching_identity(tmp_path: Path) -> None:
    """Judge identity agreement cannot substitute for matching requested controls."""
    plan, executions, events = _native_batch(tmp_path)
    last = executions[1]
    judge = NumericJudge(last.definition, last.request, 0.1, events)
    judge.parameters = plan.parameters.model_copy(update={"timeout_seconds": 60})
    assert judge.identity == plan.judge
    result = asyncio.run(execute_native_calibration(plan, (executions[0], replace(last, judge=judge))))
    assert result.blocker.code == "invalid_calibration_input"
    assert result.judge_invocation_count == 0 and events == []
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


def test_native_batch_safety_precedes_all_judge_properties(tmp_path: Path) -> None:
    """A later unsafe probe prevents even the first judge's metadata access."""
    plan, executions, events = _native_batch(tmp_path)

    class UnreadableJudge:
        """Observe any capability attribute access before whole-batch admission."""

        def __getattribute__(self, name: str) -> object:
            events.append("judge_attribute")
            raise AssertionError(f"unexpected judge attribute access: {name}")

    first = replace(executions[0], judge=UnreadableJudge())
    last = replace(executions[1], inputs=replace(executions[1].inputs, safety_evidence=None))
    rejected = asyncio.run(execute_native_calibration(plan, (first, last)))
    assert rejected.status == "blocked" and rejected.blocker.code != "invalid_calibration_input"
    assert rejected.judge_invocation_count == 0 and events == []
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


@pytest.mark.parametrize("drift_index", [0, 1])
@pytest.mark.parametrize("field", ["identity", "parameters"])
@pytest.mark.parametrize("error_type", [RuntimeError, AssertionError])
def test_native_batch_metadata_failure_is_a_blocker(
    tmp_path: Path, drift_index: int, field: str, error_type: type[Exception]
) -> None:
    """Host property exceptions stay private and cannot escape a blocked receipt."""
    plan, executions, events = _native_batch(tmp_path)

    class FailingJudge:
        """Raise an inert private exception from the selected metadata property."""

        @property
        def identity(self) -> object:
            if field == "identity":
                raise error_type("synthetic-private-detail")
            return plan.judge

        @property
        def parameters(self) -> object:
            raise error_type("synthetic-private-detail")

        async def judge(self, inputs: object) -> object:
            raise AssertionError("metadata rejection must precede judgment")

        async def cleanup(self) -> None:
            raise AssertionError("metadata rejection must precede cleanup")

    frames = tuple(
        replace(item, judge=FailingJudge()) if index == drift_index else item for index, item in enumerate(executions)
    )
    rejected = asyncio.run(execute_native_calibration(plan, frames))
    assert rejected.status == "blocked" and rejected.judge_invocation_count == 0 and events == []
    assert "synthetic-private-detail" not in rejected.model_dump_json()
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


def test_native_batch_admission_preserves_caller_cancellation(tmp_path: Path) -> None:
    """Cancellation of the caller cannot become an ordinary blocked receipt."""
    plan, executions, events = _native_batch(tmp_path)

    async def cancel_during_admission() -> None:
        """Request cancellation while metadata is read through the normal boundary."""
        task: asyncio.Task[NativeCalibrationReceipt]

        class CancellingJudge:
            """Cancel the outer caller without dispatching any provider work."""

            @property
            def identity(self) -> object:
                task.cancel()
                return plan.judge

            @property
            def parameters(self) -> object:
                return plan.parameters

            async def judge(self, inputs: object) -> object:
                raise AssertionError("caller cancellation must precede judgment")

            async def cleanup(self) -> None:
                raise AssertionError("caller cancellation must precede cleanup")

        frames = (replace(executions[0], judge=CancellingJudge()), executions[1])
        task = asyncio.create_task(execute_native_calibration(plan, frames))
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

    asyncio.run(cancel_during_admission())
    assert events == []
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


@pytest.mark.parametrize("target", ["direct", "owner"])
@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("callback", ["judge", "cleanup"])
@pytest.mark.parametrize("fault", ["missing", "noncallable", "synchronous", "signature", "valid"])
def test_native_batch_rejects_actual_callbacks(
    tmp_path: Path, target: str, index: int, callback: str, fault: str
) -> None:
    """Reject malformed real capabilities, not merely their valid facade methods."""
    plan, executions, events = _native_batch(tmp_path)
    item = executions[index]
    if target == "direct":
        numeric = NumericJudge(item.definition, item.request, 0.9 if index == 0 else 0.1, events)
        capability = SimpleNamespace(
            identity=plan.judge, parameters=plan.parameters, judge=numeric.judge, cleanup=numeric.cleanup
        )
        if fault == "missing":
            delattr(capability, callback)
        judge = capability
    else:

        class CallbackOwner(CodexJudgeAdapter):
            """Represent a supported owner whose selected callback is unavailable."""

            def __getattribute__(self, name: str) -> object:
                if fault == "missing" and name == callback:
                    raise AttributeError("synthetic missing callback")
                return super().__getattribute__(name)

        folder = tmp_path / ("judge" + str(index))
        capability = CallbackOwner(
            folder / "codex-fixture",
            folder,
            CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()),
            "Rubric",
            retain_result=_retain,
        )
        judge = CodexCalibrationJudgeAdapter(capability)

    def synchronous(*args: object) -> None:
        """A callable with compatible arguments still lacks asynchronous semantics."""
        return None

    async def wrong_judge() -> None:
        """Judges must accept their execution input."""

    async def wrong_cleanup(required: object) -> None:
        """Cleanup must accept no arguments."""

    if fault not in {"missing", "valid"}:
        malformed = {
            "noncallable": None,
            "synchronous": synchronous,
            "signature": wrong_judge if callback == "judge" else wrong_cleanup,
        }
        setattr(capability, callback, malformed[fault])
    frames = tuple(
        replace(frame, judge=judge) if position == index else frame for position, frame in enumerate(executions)
    )
    rejected = asyncio.run(execute_native_calibration(plan, frames))
    if fault == "valid":
        assert rejected.status == "pass" and rejected.judge_invocation_count == 2
        assert events.count("provider") == 2
        return
    assert rejected.judge_invocation_count == 0 and events == []
    assert rejected.status == "blocked" and rejected.blocker.code == "invalid_calibration_input"
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("cleanup_result", [None, False, 0, "synthetic-invalid-cleanup"])
def test_native_wrapper_cleanup_result_is_not_discarded(tmp_path: Path, index: int, cleanup_result: object) -> None:
    """Keep runtime cleanup violations visible with honest partial-execution evidence."""
    plan, executions, events = _native_batch(tmp_path)

    class CleanupResultOwner(CodexJudgeAdapter):
        """Close actual controlled resources before returning the selected result."""

        async def cleanup(self) -> object:
            await super().cleanup()
            return cleanup_result

    folder = tmp_path / ("judge" + str(index))
    owner = CleanupResultOwner(
        folder / "codex-fixture",
        folder,
        CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()),
        "Rubric",
        retain_result=_retain,
    )
    frames = tuple(
        replace(item, judge=CodexCalibrationJudgeAdapter(owner)) if position == index else item
        for position, item in enumerate(executions)
    )
    result = asyncio.run(execute_native_calibration(plan, frames))
    if cleanup_result is None:
        assert result.status == "pass" and result.judge_invocation_count == 2
        assert events.count("provider") == 2
        return
    assert result.status == "blocked" and result.blocker.code == "calibration_execution_incomplete"
    assert result.judge_execution_performed and result.judge_invocation_count == index + 1
    assert len(result.results) == index and events.count("provider") == index + 1
    assert "synthetic-invalid-cleanup" not in result.model_dump_json()
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    fresh_plan, fresh, _ = _native_batch(recovery)
    assert asyncio.run(execute_native_calibration(fresh_plan, fresh)).status == "pass"


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_native_wrapper_cleanup_preserves_raised_failure(tmp_path: Path, error_type: type[BaseException]) -> None:
    """Return validation cannot replace an owner's exception or cancellation."""
    _native_batch(tmp_path)
    failure = error_type("synthetic-cleanup-control")

    class FailingCleanupOwner(CodexJudgeAdapter):
        """Close controlled resources before raising the original failure."""

        async def cleanup(self) -> None:
            await super().cleanup()
            raise failure

    folder = tmp_path / "judge0"
    owner = FailingCleanupOwner(
        folder / "codex-fixture",
        folder,
        CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()),
        "Rubric",
        retain_result=_retain,
    )
    with pytest.raises(error_type) as raised:
        asyncio.run(CodexCalibrationJudgeAdapter(owner).cleanup())
    assert raised.value is failure


@pytest.mark.parametrize("change", ["identity", "parameters"])
def test_native_judge_drift_after_batch_admission_still_blocks(tmp_path: Path, change: str) -> None:
    """Whole-batch admission does not replace the later per-probe drift guard."""
    plan, executions, events = _native_batch(tmp_path)
    first, last = executions
    judge = NumericJudge(last.definition, last.request, 0.1, events)
    judge.parameters = plan.parameters
    complete = first.provider.complete

    async def change_after_dispatch(request: object, payload: object) -> object:
        """Simulate a host capability changing after the first provider request."""
        result = await complete(request, payload)
        if change == "identity":
            judge.identity = judge.identity.model_copy(update={"model_id": "changed-model"})
        else:
            judge.parameters = plan.parameters.model_copy(update={"timeout_seconds": 60})
        return result

    first.provider.complete = change_after_dispatch
    rejected = asyncio.run(execute_native_calibration(plan, (first, replace(last, judge=judge))))
    assert rejected.status == "blocked" and rejected.judge_invocation_count == 1
    assert events.count("provider") == 1 and "numeric_judge" not in events
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    fresh_plan, fresh, _ = _native_batch(recovery)
    assert asyncio.run(execute_native_calibration(fresh_plan, fresh)).status == "pass"


@pytest.mark.parametrize("representation", ["raw", "typed", "copied"])
def test_native_mcp_names_reject_credentials_before_receipt_retention(tmp_path: Path, representation: str) -> None:
    """Credential-shaped configuration names cannot enter public native receipts."""
    plan, executions, events = _native_batch(tmp_path)
    name = "ghp_" + "a" * 36  # Inert synthetic pattern; no real credential.
    parameters = plan.parameters.model_copy(update={"disabled_mcp_servers": (name,)})
    raw = plan.model_dump(mode="json")
    raw["parameters"] = parameters.model_dump(mode="json")
    raw["judge"]["adapter_version_or_digest"] = canonical_json_sha256(
        {
            "settings": parameters.model_dump(mode="json", exclude={"schema_version"}),
            "rubric_sha256": plan.rubric_sha256,
        }
    )
    candidate: object = raw
    if representation != "raw":
        candidate = plan.model_copy(update={"parameters": parameters, "judge": plan.judge.model_validate(raw["judge"])})
        if representation == "typed":
            with pytest.raises(ValidationError):
                NativeCalibrationPlan.model_validate(candidate)
    result = asyncio.run(execute_native_calibration(candidate, executions))
    assert result.status == "blocked" and result.blocker.code == "invalid_calibration_input"
    assert result.plan is None and name not in result.model_dump_json()
    assert result.judge_invocation_count == 0 and events == []


@pytest.mark.parametrize("bare_delegate", [False, True])
def test_native_wrappers_cannot_hide_single_use_delegate_alias(tmp_path: Path, bare_delegate: bool) -> None:
    """Reject delegate aliases across the whole schedule before any provider work."""
    plan, executions, events = _native_batch(tmp_path)
    delegate = executions[0].judge.capability_owner()
    alias = delegate if bare_delegate else CodexCalibrationJudgeAdapter(delegate)
    aliased = (executions[0], replace(executions[1], judge=alias))
    result = asyncio.run(execute_native_calibration(plan, aliased))
    assert result.status == "blocked" and result.blocker.code == "calibration_capability_reuse"
    assert result.judge_invocation_count == 0 and events == []
    # Rejection must leave the original independent schedule usable.
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


@pytest.mark.parametrize("bare_index", [0, 1])
def test_native_bare_judge_rejected_before_dispatch(tmp_path: Path, bare_index: int) -> None:
    """Matching settings cannot admit a judge without numeric calibration verdicts."""
    plan, executions, events = _native_batch(tmp_path)
    delegate = executions[bare_index].judge.capability_owner()
    assert delegate.identity == plan.judge and delegate.parameters == plan.parameters
    frames = tuple(
        replace(execution, judge=delegate) if index == bare_index else execution
        for index, execution in enumerate(executions)
    )
    result = asyncio.run(execute_native_calibration(plan, frames))
    assert result.status == "blocked" and result.blocker.code == "invalid_calibration_execution"
    assert not result.judge_execution_performed and result.judge_invocation_count == 0
    assert events == []
    # Admission leaves every original adapter available for a valid run.
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


@pytest.mark.parametrize("nested_index", [0, 1])
def test_native_nested_wrapper_rejected_before_dispatch(tmp_path: Path, nested_index: int) -> None:
    """Reject unsupported nested delegates before any probe consumes provider work."""
    plan, executions, events = _native_batch(tmp_path)
    nested = CodexCalibrationJudgeAdapter(delegate=executions[nested_index].judge)
    # The unsupported nesting forwards matching metadata; identity alone cannot reject it.
    assert nested.identity == plan.judge and nested.parameters == plan.parameters
    frames = tuple(
        replace(execution, judge=nested) if index == nested_index else execution
        for index, execution in enumerate(executions)
    )
    result = asyncio.run(execute_native_calibration(plan, frames))
    assert result.status == "blocked" and result.blocker.code == "invalid_calibration_execution"
    assert result.judge_invocation_count == 0 and not result.judge_execution_performed
    assert events == []
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


def test_native_wrapper_owner_rejected_without_attribute_access(tmp_path: Path) -> None:
    """Malformed wrapped owners cannot execute attributes during admission."""
    plan, executions, events = _native_batch(tmp_path)

    class UnreadableOwner:
        """Make even class-identity fallback observable to the regression."""

        def __getattribute__(self, name: str) -> object:
            events.append("owner_attribute")
            raise AssertionError(f"unexpected owner attribute access: {name}")

    wrapped = CodexCalibrationJudgeAdapter(delegate=UnreadableOwner())
    result = asyncio.run(execute_native_calibration(plan, (replace(executions[0], judge=wrapped), executions[1])))
    assert result.blocker.code == "invalid_calibration_execution" and events == []
    assert result.judge_invocation_count == 0 and not result.judge_execution_performed
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


def test_native_mcp_public_names_remain_accepted(tmp_path: Path) -> None:
    """Ordinary disabled-server keys remain usable with an updated identity."""
    plan, _, _ = _native_batch(tmp_path)
    parameters = plan.parameters.model_copy(update={"disabled_mcp_servers": ("docs-local", "tools_01")})
    raw = plan.model_dump(mode="json")
    raw["parameters"] = parameters.model_dump(mode="json")
    raw["judge"]["adapter_version_or_digest"] = canonical_json_sha256(
        {
            "settings": parameters.model_dump(mode="json", exclude={"schema_version"}),
            "rubric_sha256": plan.rubric_sha256,
        }
    )
    assert NativeCalibrationPlan.model_validate(raw).parameters.disabled_mcp_servers == ("docs-local", "tools_01")


def test_native_wrapper_subclass_cannot_invoke_properties_during_admission(tmp_path: Path) -> None:
    """Only the concrete ownership record is inspected before safety admission."""
    plan, executions, events = _native_batch(tmp_path)

    class UnsafeWrapper(CodexCalibrationJudgeAdapter):
        """Fail if admission invokes an overridable ownership callback."""

        def capability_owner(self) -> CodexJudgeAdapter:
            events.append("ownership_callback")
            raise AssertionError("admission must not invoke this callback")

    alias = UnsafeWrapper(executions[0].judge.capability_owner())
    result = asyncio.run(execute_native_calibration(plan, (replace(executions[0], judge=alias), executions[1])))
    assert result.blocker.code == "invalid_calibration_execution" and events == []


def test_native_wrapper_retains_keyword_construction_and_fixed_owner(tmp_path: Path) -> None:
    """Preserve the delegate keyword while preventing ownership reassignment."""
    _, executions, _ = _native_batch(tmp_path)
    delegate = executions[0].judge.capability_owner()
    wrapped = CodexCalibrationJudgeAdapter(delegate=delegate)
    assert wrapped.capability_owner() is delegate
    with pytest.raises(AttributeError):
        wrapped.delegate = executions[1].judge.capability_owner()


def test_native_forged_parameters_and_partial_receipt_are_rejected(tmp_path: Path) -> None:
    plan, executions, events = _native_batch(tmp_path)
    forged = plan.model_copy(update={"parameters": plan.parameters.model_copy(update={"temperature": 0.0})})
    result = asyncio.run(execute_native_calibration(forged, executions))
    assert result.blocker.code == "invalid_calibration_input" and events == []
    passed = asyncio.run(execute_native_calibration(plan, executions))
    raw = passed.model_dump(mode="json")
    raw["results"] = raw["results"][:1]
    with pytest.raises(ValidationError):
        NativeCalibrationReceipt.model_validate(raw)


def test_packaged_parameter_schema_is_additive() -> None:
    parameters = CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()).calibration_parameters()
    # Native settings stay provider-owned; only the calibration families enter the registry.
    assert CodexNativeJudgeParameters.model_validate(parameters.model_dump(mode="json")) == parameters
    raw = json.loads(parameters.model_dump_json())
    raw["temperature"] = 0.0
    with pytest.raises(ValidationError):
        CodexNativeJudgeParameters.model_validate(raw)


def test_native_safety_and_settings_drift_do_not_create_judgments(tmp_path: Path) -> None:
    plan, executions, events = _native_batch(tmp_path)
    bad = replace(executions[0], inputs=replace(executions[0].inputs, safety_evidence=None))
    rejected = asyncio.run(execute_native_calibration(plan, (bad, executions[1])))
    assert rejected.status == "blocked" and rejected.judge_invocation_count == 0 and events == []
    raw = plan.model_dump(mode="json")
    raw["parameters"]["timeout_seconds"] = 60
    raw["judge"]["adapter_version_or_digest"] = CodexNativeJudgeParameters.model_validate(raw["parameters"])
    raw["judge"]["adapter_version_or_digest"] = canonical_json_sha256(
        {
            "settings": raw["judge"]["adapter_version_or_digest"].model_dump(mode="json", exclude={"schema_version"}),
            "rubric_sha256": raw["rubric_sha256"],
        }
    )
    drifted = asyncio.run(execute_native_calibration(raw, executions))
    assert drifted.status == "blocked" and drifted.judge_invocation_count == 0


def test_native_policy_failure_retains_complete_observed_results(tmp_path: Path) -> None:
    plan, executions, _ = _native_batch(tmp_path)
    _executable(tmp_path / "judge1", "print(" + repr(_events(0.9, executions[1].definition.semantic_signal_ids)) + ")")
    result = asyncio.run(execute_native_calibration(plan, executions))
    assert result.blocker.code == "calibration_policy_failed"
    assert len(result.results) == result.judge_invocation_count == 2
    SchemaRegistry().validate("native-calibration.v1", result.model_dump(mode="json"))


@pytest.mark.parametrize("field", ["rubric_sha256", "assertion_contract_sha256"])
def test_native_rubric_drift_blocks_before_dispatch(tmp_path: Path, field: str) -> None:
    plan, executions, events = _native_batch(tmp_path)
    forged = plan.model_copy(update={field: "0" * 64})
    result = asyncio.run(execute_native_calibration(forged, executions))
    assert result.status == "blocked" and result.judge_invocation_count == 0 and events == []
    assert asyncio.run(execute_native_calibration(plan, executions)).status == "pass"


def test_native_retention_failure_cannot_create_calibration(tmp_path: Path) -> None:
    plan, executions, events = _native_batch(tmp_path)

    async def rejected_retention(ref: str, payload: bytes) -> None:
        raise OSError("synthetic retention unavailable")

    executable = tmp_path / "judge0" / "codex-fixture"
    delegate = CodexJudgeAdapter(
        executable,
        executable.parent,
        CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()),
        "Rubric",
        retain_result=rejected_retention,
    )
    frames = (replace(executions[0], judge=CodexCalibrationJudgeAdapter(delegate)), *executions[1:])
    result = asyncio.run(execute_native_calibration(plan, frames))
    assert result.status == "blocked" and result.judge_invocation_count == 1 and result.results == ()
    assert events.count("provider") == 1
