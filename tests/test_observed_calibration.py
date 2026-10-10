"""Actual controlled calibration invocation, hidden labels, rejection and recovery."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import UserDict, UserList
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError, model_serializer
from test_live_selected_case import _Provider, _setup
from test_selected_case_evaluation import _evidence, _safety_for

from skills_sdk.cli.main import main
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.observed_calibration import (
    CalibrationProbeExecution,
    CalibrationTrialAdapters,
    execute_scorer_calibration,
)
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.models.observed_calibration import (
    CalibrationJudgeVerdict,
    ObservedCalibrationPlan,
    ObservedCalibrationReceipt,
)
from skills_sdk.models.scorer_quality import ScorerJudgeParameters


class NumericJudge:
    """Controlled callback returns a bound verdict, never reads held-out labels."""

    def __init__(self, definition: object, request: object, score: float, events: list[str]) -> None:
        self.definition = definition
        self.request = request
        self.score = score
        self.events = events
        self.identity = request.provider
        self.parameters = ScorerJudgeParameters(model=self.identity.model_id, temperature=0.0, trial_count=1)

    async def judge(self, inputs: object) -> object:
        self.events.append("numeric_judge")
        assert "expected_label" not in inputs.__dataclass_fields__
        assert "expected_label" not in str(inputs.request.model_dump(mode="json"))
        evidence = _evidence(self.definition, self.request, inputs.output_text)
        if self.score < 0.5:
            evidence = evidence.model_copy(update={"satisfied_assertion_ids": ()})
        return CalibrationJudgeVerdict(evidence=evidence, score=self.score)

    async def cleanup(self) -> None:
        self.events.append("numeric_judge_cleanup")


def _batch(root: Path) -> tuple[ObservedCalibrationPlan, tuple[CalibrationProbeExecution, ...], list[str]]:
    definition, payload, request, events = _setup(root)
    texts = ("behavior preserved", "incorrect held-out output")
    scores = (0.9, 0.1)
    ids = ("held-out-positive", "held-out-negative")
    plan = ObservedCalibrationPlan.model_validate(
        {
            "candidate": request.candidate.model_dump(mode="json"),
            "scorer": {
                "candidate": request.candidate.model_dump(mode="json"),
                "scorer_id": "fixture-calibrator",
                "scorer_type": "llm_judge",
                "version_or_digest": "v1",
                "pass_threshold": 0.5,
                "deterministic_checks_first": True,
                "calibration_required": True,
                "calibration_probe_ids": list(ids),
            },
            "judge": request.provider.model_dump(mode="json"),
            "parameters": {"model": request.provider.model_id, "temperature": 0.0, "trial_count": 1},
            "assertion_contract_sha256": definition.assertion_contract_sha256,
            "policy": {
                "threshold": 0.5,
                "minimum_examples": 2,
                "minimum_true_positives": 1,
                "minimum_true_negatives": 1,
                "max_false_positives": 0,
                "max_false_negatives": 0,
            },
            "probes": [
                {"probe_id": name, "output_sha256": hashlib.sha256(text.encode()).hexdigest(), "expected_label": label}
                for name, text, label in zip(ids, texts, ("pass", "fail"), strict=True)
            ],
        }
    )
    inputs = SelectedCaseExecutionInput(payload, _safety_for(definition, request))
    executions = tuple(
        CalibrationProbeExecution(
            definition,
            request,
            inputs,
            _Provider(request, events, text),
            NumericJudge(definition, request, score, events),
        )
        for text, score in zip(texts, scores, strict=True)
    )
    return plan, executions, events


def test_numeric_calibration_rejects_non_none_cleanup_and_recovers(tmp_path: Path) -> None:
    """A swallowed cleanup failure must not qualify held-out judgments."""
    plan, executions, events = _batch(tmp_path)

    class InvalidCleanupJudge(NumericJudge):
        """Expose a numeric judge whose cleanup violates the adapter contract."""

        async def cleanup(self) -> object:
            """Record cleanup and return a non-None result to trigger rejection."""
            self.events.append("invalid_cleanup")
            return False

    first = executions[0]
    invalid = InvalidCleanupJudge(first.definition, first.request, first.judge.score, events)
    broken = (replace(first, judge=invalid), *executions[1:])
    rejected = asyncio.run(execute_scorer_calibration(plan, broken))
    assert rejected.status == "blocked"
    assert rejected.blocker.code == "calibration_execution_incomplete"
    assert rejected.judge_invocation_count == 1
    assert rejected.results == ()
    recovered = asyncio.run(execute_scorer_calibration(plan, executions))
    assert recovered.status == "pass"


def _host_input(plan: ObservedCalibrationPlan, executions: tuple[CalibrationProbeExecution, ...]) -> dict[str, object]:
    """Retain controlled fixture inputs for source and installed CLI proof."""
    return {
        "plan": plan.model_dump(mode="json"),
        "executions": [
            {
                "case_id": item.request.case_id,
                "mode": "release",
                "request": item.request.model_dump(mode="json"),
                "input_payload": item.inputs.payload,
                "safety_evidence": item.inputs.safety_evidence.model_dump(mode="json"),
                "provider": {
                    "descriptor": item.provider.descriptor.model_dump(mode="json"),
                    "output_text": item.provider.text,
                    "evidence_refs": ["evidence/provider-result.json"],
                },
                "judge": {
                    "identity": item.judge.identity.model_dump(mode="json"),
                    "parameters": item.judge.parameters.model_dump(mode="json"),
                    "verdict": {
                        "evidence": _evidence(item.definition, item.request, item.provider.text).model_dump(
                            mode="json"
                        ),
                        "score": item.judge.score,
                    },
                },
            }
            for item in executions
        ],
    }


def test_actual_numeric_invocation_and_hidden_labels(tmp_path: Path) -> None:
    plan, executions, events = _batch(tmp_path)
    result = asyncio.run(execute_scorer_calibration(plan, executions))
    assert result.status == "pass" and result.judge_execution_performed and not result.promotion_authorized
    assert events.count("numeric_judge") == 2
    assert [item.predicted_label for item in result.results] == ["pass", "fail"]


def test_incomplete_batch_rejects_before_dispatch_and_recovers(tmp_path: Path) -> None:
    plan, executions, events = _batch(tmp_path)
    rejected = asyncio.run(execute_scorer_calibration(plan, executions[:1]))
    assert rejected.status == "blocked" and events == [] and not rejected.judge_execution_performed
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


def test_false_positive_blocks_after_actual_execution_then_recovers(tmp_path: Path) -> None:
    plan, executions, events = _batch(tmp_path)
    executions[1].judge.score = 0.9
    rejected = asyncio.run(execute_scorer_calibration(plan, executions))
    assert rejected.status == "blocked" and rejected.blocker.code == "calibration_policy_failed"
    assert rejected.judge_execution_performed and events.count("numeric_judge") == 2
    executions[1].judge.score = 0.1
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


def _repeat_trials(
    plan: ObservedCalibrationPlan, executions: tuple[CalibrationProbeExecution, ...]
) -> tuple[CalibrationProbeExecution, ...]:
    """Align fixture judge settings and allocate distinct adapters for later trials."""
    frames = []
    for item in executions:
        item.judge.parameters = plan.parameters
        pairs = []
        for _ in range(plan.parameters.trial_count - 1):
            judge = type(item.judge)(item.definition, item.request, item.judge.score, item.judge.events)
            judge.parameters = plan.parameters
            pairs.append(
                CalibrationTrialAdapters(_Provider(item.request, item.provider.events, item.provider.text), judge)
            )
        frames.append(replace(item, trial_adapters=tuple(pairs)))
    return tuple(frames)


def test_declared_trials_execute_each_probe_and_retain_order(tmp_path: Path) -> None:
    """Verify every declared probe trial executes and preserves probe-major ordering."""
    plan, executions, events = _batch(tmp_path)
    payload = plan.model_dump(mode="json")
    payload["parameters"]["trial_count"] = 2
    plan = ObservedCalibrationPlan.model_validate(payload)
    executions = _repeat_trials(plan, executions)
    result = asyncio.run(execute_scorer_calibration(plan, executions))
    assert result.status == "pass" and len(result.results) == 4
    assert [item.trial_index for item in result.results] == [0, 1, 0, 1]
    assert events.count("numeric_judge") == 4


def test_private_copied_identity_rejected_before_callback(tmp_path: Path) -> None:
    plan, executions, events = _batch(tmp_path)
    forged = plan.model_copy(update={"scorer": plan.scorer.model_copy(update={"scorer_id": "token=private-value"})})
    result = asyncio.run(execute_scorer_calibration(forged, executions))
    assert result.status == "blocked" and result.plan is None and events == []
    assert "private-value" not in result.model_dump_json()
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


def test_copied_contracts_and_false_only_fields_revalidate(tmp_path: Path) -> None:
    plan, executions, _ = _batch(tmp_path)
    result = asyncio.run(execute_scorer_calibration(plan, executions))
    for update in ({"schema_version": "invalid"}, {"assertion_contract_sha256": "invalid"}):
        with pytest.raises(ValidationError):
            ObservedCalibrationPlan.model_validate(plan.model_copy(update=update))
    for update in ({"schema_version": "invalid"}, {"promotion_authorized": True}, {"mutation_performed": True}):
        with pytest.raises(ValidationError):
            ObservedCalibrationReceipt.model_validate(result.model_copy(update=update))
    for field in ("promotion_authorized", "mutation_performed", "external_authenticity_verified"):
        for invalid in (0, 1, "false", None):
            raw = result.model_dump(mode="json")
            raw[field] = invalid
            with pytest.raises(ValidationError):
                ObservedCalibrationReceipt.model_validate(raw)
            with pytest.raises(ContractError):
                SchemaRegistry().validate("observed-calibration.v1", raw)
    for member, update in (
        (plan.probes[0], {"expected_label": "invalid"}),
        (result.results[0], {"score": True}),
        (
            CalibrationJudgeVerdict(
                evidence=_evidence(executions[0].definition, executions[0].request, "behavior preserved"), score=0.9
            ),
            {"score": float("nan")},
        ),
    ):
        with pytest.raises(ValidationError):
            type(member).model_validate(member.model_copy(update=update))
    assert ObservedCalibrationReceipt.model_validate(result) == result


def test_invalid_later_request_stops_entire_batch_then_recovers(tmp_path: Path) -> None:
    plan, executions, events = _batch(tmp_path)
    for field, value in (("case_id", "other-case"), ("scenario_set_id", "other-set")):
        forged = executions[1].request.model_copy(update={field: value})
        changed = (executions[0], replace(executions[1], request=forged))
        rejected = asyncio.run(execute_scorer_calibration(plan, changed))
        assert rejected.status == "blocked" and rejected.judge_invocation_count == 0 and events == []
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


class PropertyFailureJudge(NumericJudge):
    """Obtaining a capability is not invoking it."""

    @property
    def judge(self) -> object:
        self.events.append("judge_property")
        raise ValueError("unavailable callback")


class CallbackFailureJudge(NumericJudge):
    """A failed actual invocation must still be counted."""

    async def judge(self, inputs: object) -> object:
        self.events.append("failed_callback")
        raise ValueError("callback failed")


@pytest.mark.parametrize("adapter,count", [(PropertyFailureJudge, 0), (CallbackFailureJudge, 1)])
def test_failure_invocation_accounting_and_recovery(tmp_path: Path, adapter: type, count: int) -> None:
    plan, executions, events = _batch(tmp_path)
    judge = adapter(executions[0].definition, executions[0].request, 0.9, events)
    rejected = asyncio.run(execute_scorer_calibration(plan, (replace(executions[0], judge=judge), executions[1])))
    assert rejected.status == "blocked" and rejected.judge_invocation_count == count
    assert rejected.judge_execution_performed is (count > 0)
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


class SettingsDriftJudge(NumericJudge):
    """A changed parameter cannot retain a previously checked binding."""

    async def judge(self, inputs: object) -> object:
        self.parameters = self.parameters.model_copy(update={"temperature": 1.0})
        return await super().judge(inputs)


def test_settings_drift_blocks_returned_verdict_and_recovers(tmp_path: Path) -> None:
    plan, executions, events = _batch(tmp_path)
    judge = SettingsDriftJudge(executions[0].definition, executions[0].request, 0.9, events)
    rejected = asyncio.run(execute_scorer_calibration(plan, (replace(executions[0], judge=judge), executions[1])))
    assert rejected.status == "blocked" and rejected.judge_invocation_count == 1 and rejected.results == ()
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


def test_blocked_first_stop_accounting_rejects_impossible_history(tmp_path: Path) -> None:
    plan, executions, _ = _batch(tmp_path)
    legitimate = asyncio.run(execute_scorer_calibration(plan, executions[:1]))
    forged = legitimate.model_copy(update={"judge_invocation_count": 2, "judge_execution_performed": True})
    with pytest.raises(ValidationError):
        ObservedCalibrationReceipt.model_validate(forged)
    assert ObservedCalibrationReceipt.model_validate(legitimate) == legitimate


@pytest.mark.parametrize(
    "code",
    [
        "calibration_policy_failed",
        "calibration_execution_coverage",
        "calibration_request_mismatch",
        "invalid_calibration_input",
        "calibration_execution_incomplete",
        "calibration_execution_failed",
    ],
)
def test_blocker_code_cannot_relabel_complete_passing_evidence(tmp_path: Path, code: str) -> None:
    plan, executions, _ = _batch(tmp_path)
    passed = asyncio.run(execute_scorer_calibration(plan, executions))
    raw = passed.model_dump(mode="json")
    raw.update(status="blocked", blocker={"code": code, "message": "blocked"})
    for value in (raw, passed.model_copy(update={"status": "blocked", "blocker": raw["blocker"]})):
        with pytest.raises(ValidationError):
            ObservedCalibrationReceipt.model_validate(value)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("observed-calibration.v1", raw)
    assert ObservedCalibrationReceipt.model_validate(passed) == passed


def test_policy_failure_requires_complete_failed_policy_and_recovers(tmp_path: Path) -> None:
    plan, executions, _ = _batch(tmp_path)
    incomplete = asyncio.run(execute_scorer_calibration(plan, executions[:1]))
    raw = incomplete.model_dump(mode="json")
    raw["blocker"] = {"code": "calibration_policy_failed", "message": "blocked"}
    with pytest.raises(ValidationError):
        ObservedCalibrationReceipt.model_validate(raw)
    raw["plan"] = None
    with pytest.raises(ValidationError):
        ObservedCalibrationReceipt.model_validate(raw)
    executions[1].judge.score = 0.9
    failed = asyncio.run(execute_scorer_calibration(plan, executions))
    assert failed.blocker.code == "calibration_policy_failed"
    assert ObservedCalibrationReceipt.model_validate(failed) == failed
    SchemaRegistry().validate("observed-calibration.v1", failed.model_dump(mode="json"))
    executions[1].judge.score = 0.1
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


class LastTrialFailureJudge(NumericJudge):
    """Retain genuine final-trial failure while rejecting fabricated completion."""

    async def judge(self, inputs: object) -> object:
        previous = self.events.count("last_trial_judge")
        self.events.append("last_trial_judge")
        if previous:
            raise ValueError("last trial failed")
        return await super().judge(inputs)


def test_final_trial_failure_retains_complete_invocation_count(tmp_path: Path) -> None:
    """Count the failing final invocation, retain earlier results and accept recovery."""
    plan, executions, events = _batch(tmp_path)
    raw = plan.model_dump(mode="json")
    raw["parameters"]["trial_count"] = 2
    plan = ObservedCalibrationPlan.model_validate(raw)
    judge = LastTrialFailureJudge(executions[1].definition, executions[1].request, 0.1, events)
    changed = (executions[0], replace(executions[1], judge=judge))
    changed = _repeat_trials(plan, changed)
    blocked = asyncio.run(execute_scorer_calibration(plan, changed))
    assert blocked.status == "blocked" and blocked.judge_invocation_count == 4 and len(blocked.results) == 3
    assert ObservedCalibrationReceipt.model_validate(blocked) == blocked
    SchemaRegistry().validate("observed-calibration.v1", blocked.model_dump(mode="json"))
    executions = _repeat_trials(plan, executions)
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


@pytest.mark.parametrize(
    "update",
    [
        {"code": "token=private-value"},
        {"message": "token=private-value"},
        {"evidence_refs": ("/absolute/private-file",)},
    ],
)
def test_copied_blocker_cannot_bypass_private_data_boundary(tmp_path: Path, update: dict[str, object]) -> None:
    plan, executions, _ = _batch(tmp_path)
    blocked = asyncio.run(execute_scorer_calibration(plan, executions[:1]))
    forged_blocker = blocked.blocker.model_copy(update=update)
    for envelope in (
        blocked.model_copy(update={"blocker": forged_blocker}),
        {**blocked.model_dump(mode="json"), "blocker": forged_blocker},
    ):
        with pytest.raises(ValidationError):
            ObservedCalibrationReceipt.model_validate(envelope)
    raw = {**blocked.model_dump(mode="json"), "blocker": forged_blocker.model_dump(mode="json")}
    with pytest.raises(ContractError):
        SchemaRegistry().validate("observed-calibration.v1", raw)
    assert ObservedCalibrationReceipt.model_validate(blocked) == blocked
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


@pytest.mark.parametrize("field", ["candidate", "scorer", "judge", "parameters", "policy"])
def test_nested_copied_unknown_fields_reject_before_dispatch(tmp_path: Path, field: str) -> None:
    plan, executions, events = _batch(tmp_path)
    raw = plan.model_dump(mode="python")
    raw[field] = getattr(plan, field).model_copy(update={"unexpected": "value"})
    with pytest.raises(ValidationError):
        ObservedCalibrationPlan.model_validate(raw)
    rejected = asyncio.run(execute_scorer_calibration(plan.model_copy(update={field: raw[field]}), executions))
    assert rejected.status == "blocked" and events == []
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


@pytest.mark.parametrize(
    "field,key",
    [
        ("parameters", "trial_count"),
        ("parameters", "temperature"),
        ("policy", "minimum_examples"),
        ("policy", "threshold"),
    ],
)
def test_copied_numeric_bools_cannot_be_laundered_by_json(tmp_path: Path, field: str, key: str) -> None:
    plan, executions, events = _batch(tmp_path)
    bad = getattr(plan, field).model_copy(update={key: True})
    forged = plan.model_copy(update={field: bad})
    with pytest.raises(ValidationError):
        ObservedCalibrationPlan.model_validate(forged)
    rejected = asyncio.run(execute_scorer_calibration(forged, executions))
    assert rejected.status == "blocked" and events == []
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


class BooleanScoreJudge(NumericJudge):
    """A copied callback verdict must retain its invalid boolean provenance."""

    async def judge(self, inputs: object) -> object:
        verdict = await super().judge(inputs)
        return verdict.model_copy(update={"score": True})


def test_callback_copied_boolean_score_blocks_and_recovers(tmp_path: Path) -> None:
    plan, executions, events = _batch(tmp_path)
    judge = BooleanScoreJudge(executions[0].definition, executions[0].request, 0.9, events)
    blocked = asyncio.run(execute_scorer_calibration(plan, (replace(executions[0], judge=judge), executions[1])))
    assert blocked.status == "blocked" and blocked.judge_invocation_count == 1 and blocked.results == ()
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


def test_input_audit_bounds_cycles_and_work_preserving_valid_aliases(tmp_path: Path) -> None:
    from skills_sdk.models.observed_calibration import _audit_copied_members

    plan, executions, events = _batch(tmp_path)
    shared = [plan.candidate]
    _audit_copied_members([shared, shared])
    for _ in range(14):
        shared = [shared, shared]
    _audit_copied_members(shared)
    cycle: list[object] = []
    cycle.append(cycle)
    for malformed in (cycle, list(range(5000))):
        with pytest.raises(ValueError):
            _audit_copied_members(malformed)
        rejected = asyncio.run(execute_scorer_calibration(malformed, executions))
        assert rejected.status == "blocked" and events == []
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


def _masked_model(value: BaseModel, calls: list[str]) -> BaseModel:
    """A caller serializer must not replace raw members at a contract boundary."""

    class CallerModel(type(value)):
        @model_serializer(mode="plain")
        def mask_members(self) -> dict[str, object]:
            calls.append("serializer")
            return value.model_dump(mode="python")

    return CallerModel.model_construct(**value.__dict__)


@pytest.mark.parametrize("boundary", ["raw", "typed"])
def test_noncanonical_plan_judge_rejects_before_serialization_and_recovers(tmp_path: Path, boundary: str) -> None:
    plan, executions, events = _batch(tmp_path)
    calls: list[str] = []
    forged = _masked_model(plan.judge, calls).model_copy(update={"provider_kind": "bogus"})
    supplied = (
        {**plan.model_dump(mode="json"), "judge": forged}
        if boundary == "raw"
        else plan.model_copy(update={"judge": forged})
    )
    with pytest.raises(ValidationError):
        ObservedCalibrationPlan.model_validate(supplied)
    rejected = asyncio.run(execute_scorer_calibration(supplied, executions))
    assert rejected.blocker.code == "invalid_calibration_input" and rejected.plan is None
    assert calls == [] and events == []
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


@pytest.mark.parametrize("field", ["provider", "judge"])
@pytest.mark.parametrize("mutation", ["subclass", "bytes"])
def test_mixed_verdict_evidence_rejects_before_coercion_and_recovers(tmp_path: Path, field: str, mutation: str) -> None:
    _, executions, _ = _batch(tmp_path)
    item = executions[0]
    evidence = _evidence(item.definition, item.request, "behavior preserved")
    calls: list[str] = []
    identity = getattr(evidence, field)
    forged = (
        _masked_model(identity, calls).model_copy(update={"provider_kind": "bogus"})
        if mutation == "subclass"
        else identity.model_copy(update={"provider_id": b"synthetic-provider"})
    )
    supplied = {"evidence": {**evidence.model_dump(mode="json"), field: forged}, "score": 0.9}
    with pytest.raises(ValidationError):
        CalibrationJudgeVerdict.model_validate(supplied)
    assert calls == []
    assert CalibrationJudgeVerdict(evidence=evidence, score=0.9).evidence == evidence


@pytest.mark.parametrize("boundary", ["raw", "typed"])
def test_mapping_views_cannot_hide_nested_serializers_and_recover(tmp_path: Path, boundary: str) -> None:
    _, executions, _ = _batch(tmp_path)
    item = executions[0]
    evidence = _evidence(item.definition, item.request, "behavior preserved")
    canonical = CalibrationJudgeVerdict(evidence=evidence, score=0.9)
    calls: list[str] = []
    hidden = _masked_model(evidence.provider, calls).model_copy(update={"provider_kind": "bogus"})
    view = UserDict({**evidence.model_dump(mode="json"), "provider": hidden})
    supplied = (
        {"evidence": view, "score": 0.9} if boundary == "raw" else canonical.model_copy(update={"evidence": view})
    )
    with pytest.raises(ValidationError):
        CalibrationJudgeVerdict.model_validate(supplied)
    assert calls == []
    assert CalibrationJudgeVerdict.model_validate(canonical) == canonical


@pytest.mark.parametrize("field", ["evidence_refs", "satisfied_assertion_ids"])
@pytest.mark.parametrize("container", ["set", "view", "generator"])
def test_non_json_containers_cannot_hide_bytes_and_recover(tmp_path: Path, field: str, container: str) -> None:
    _, executions, _ = _batch(tmp_path)
    item = executions[0]
    evidence = _evidence(item.definition, item.request, "behavior preserved")
    text = b"evidence/review.json" if field == "evidence_refs" else b"preserve-behavior"
    hidden = {"set": {text}, "view": UserList([text]), "generator": iter([text])}[container]
    raw = {"evidence": {**evidence.model_dump(mode="json"), field: hidden}, "score": 0.9}
    with pytest.raises(ValidationError):
        CalibrationJudgeVerdict.model_validate(raw)
    assert CalibrationJudgeVerdict(evidence=evidence, score=0.9).evidence == evidence


@pytest.mark.parametrize("member", ["plan", "probe", "verdict", "receipt", "result"])
def test_direct_additive_subclasses_reject_before_handler_and_recover(tmp_path: Path, member: str) -> None:
    plan, executions, _ = _batch(tmp_path)
    receipt = asyncio.run(execute_scorer_calibration(plan, executions))
    item = executions[0]
    verdict = CalibrationJudgeVerdict(
        evidence=_evidence(item.definition, item.request, "behavior preserved"), score=0.9
    )
    canonical = {
        "plan": plan,
        "probe": plan.probes[0],
        "verdict": verdict,
        "receipt": receipt,
        "result": receipt.results[0],
    }[member]
    calls: list[str] = []
    with pytest.raises(ValidationError):
        type(canonical).model_validate(_masked_model(canonical, calls))
    assert calls == []
    assert type(canonical).model_validate(canonical) == canonical


class NoncanonicalVerdictJudge(NumericJudge):
    """Actual invocation cannot turn a caller subclass into canonical evidence."""

    async def judge(self, inputs: object) -> object:
        verdict = await super().judge(inputs)
        return _masked_model(verdict, self.events)


class MappingVerdictJudge(NumericJudge):
    """A mapping view must not defer hidden model validation to a frozen family."""

    async def judge(self, inputs: object) -> object:
        verdict = await super().judge(inputs)
        hidden = _masked_model(verdict.evidence.provider, self.events)
        view = UserDict({**verdict.evidence.model_dump(mode="json"), "provider": hidden})
        return {"evidence": view, "score": verdict.score}


@pytest.mark.parametrize("adapter", [NoncanonicalVerdictJudge, MappingVerdictJudge])
def test_noncanonical_callback_rejects_without_serialization_and_recovers(
    tmp_path: Path, adapter: type[NumericJudge]
) -> None:
    plan, executions, events = _batch(tmp_path)
    judge = adapter(executions[0].definition, executions[0].request, 0.9, events)
    changed = (replace(executions[0], judge=judge), executions[1])
    blocked = asyncio.run(execute_scorer_calibration(plan, changed))
    assert blocked.status == "blocked" and blocked.judge_invocation_count == 1 and blocked.results == ()
    assert "serializer" not in events
    assert asyncio.run(execute_scorer_calibration(plan, executions)).status == "pass"


def test_offline_cli_accepts_rejects_and_recovers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plan, executions, _ = _batch(tmp_path)
    path = tmp_path / "host-input.json"
    original = _host_input(plan, executions)
    arguments = [
        "eval",
        "observed-calibration",
        str(tmp_path / "simplify"),
        "--source-revision",
        plan.candidate.source_revision,
        "--host-input",
        str(path),
        "--adapter-mode",
        "supplied-offline",
        "--json",
        "--robot",
    ]
    for accepted in (True, False, True):
        payload = json.loads(json.dumps(original))
        if not accepted:
            payload["executions"][1]["safety_evidence"] = None
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert main(arguments) == (0 if accepted else 2)
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["status"] == ("pass" if accepted else "blocked")
        assert receipt["external_authenticity_verified"] is False
        assert receipt["promotion_authorized"] is False
        assert receipt["judge_invocation_count"] == (2 if accepted else 0)


@pytest.mark.parametrize("content", ['{"plan":null,"plan":null,"executions":[]}', "{}", "[]", "invalid JSON"])
def test_offline_cli_malformed_input_has_typed_blocker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str
) -> None:
    path = tmp_path / "host-input.json"
    path.write_text(content, encoding="utf-8")
    assert (
        main(
            [
                "eval",
                "observed-calibration",
                str(tmp_path),
                "--source-revision",
                "1" * 40,
                "--host-input",
                str(path),
                "--adapter-mode",
                "supplied-offline",
                "--json",
            ]
        )
        == 2
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["schema_version"] == "observed-calibration/v1"
    assert receipt["status"] == "blocked" and receipt["judge_invocation_count"] == 0
