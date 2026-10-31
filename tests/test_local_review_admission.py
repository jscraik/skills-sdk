"""Strict caller proof with synthetic host origins and real offline matched execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_matched_execution as matched_fixture
from test_matched_execution import _matched

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation import local_review_admission as service
from skills_sdk.evaluation.local_review_admission import (
    LocalReviewAuthority,
    LocalReviewExpectation,
    LocalReviewPolicy,
    execute_reviewed_matched_lane,
)
from skills_sdk.evaluation.matched_admission import MatchedCaseExecution
from skills_sdk.models.matched_comparison import MatchedComparisonPlan


class _Host:
    """Synthetic host; disk consumption outlives this Python capability instance."""

    def __init__(self, directory: Path, origins: dict[str, bytes]) -> None:
        self.directory = directory
        self.origins = origins
        self.resolutions = 0
        self.consumptions = 0

    def resolve_review(self, expected: LocalReviewExpectation) -> bytes:
        self.resolutions += 1
        return self.origins[expected.thread_id]

    def consume(self, operation_id: str, policy_sha256: str) -> bool:
        self.consumptions += 1
        path = self.directory / hashlib.sha256(operation_id.encode()).hexdigest()
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        try:
            assert os.write(fd, policy_sha256.encode()) == 64
        finally:
            os.close(fd)
        return True


def test_large_captures_preserve_plan_ingress_and_later_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = matched_fixture._plugin_definitions

    def definitions(root: Path, score: float, count: int) -> tuple[object, ...]:
        result = original(root, score, count)
        for index in range(400):
            (root / f"resource-{index}.md").write_text("Inert captured resource.\n")
        return result

    monkeypatch.setattr(matched_fixture, "_plugin_definitions", definitions)
    plan, _calibrations, batch, events = _matched(tmp_path / "packages")
    assert len(plan.plugin_scope.baseline.files) >= 400
    assert len(plan.plugin_scope.candidate.files) >= 400
    for index, incoming in enumerate((plan, plan.model_dump(mode="json"))):
        assert MatchedComparisonPlan.model_validate(incoming).digest == plan.digest
        directory = tmp_path / f"host-{index}"
        directory.mkdir()
        policy, host = _authority(plan, batch, directory)
        accesses: list[str] = []
        receipt = asyncio.run(
            execute_reviewed_matched_lane(
                incoming, "local", (), _observe(batch, accesses), authority=LocalReviewAuthority(policy, host)
            )
        )
        assert receipt.status == "blocked" and receipt.blocker.code == "invalid_matched_execution"
        assert host.consumptions == 1
        assert not accesses and not events


def _authority(plan: object, batch: tuple, directory: Path) -> tuple[LocalReviewPolicy, _Host]:
    reviews = []
    origins = {}
    now = time.time()
    for number, frame in enumerate((batch[0].baseline, batch[0].candidate)):
        capture = frame.plugin_context.validation
        report = "SYNTHETIC source review; not actual release authority"
        event = {
            "thread": {"id": f"synthetic-{number}", "kind": "codex"},
            "turns": [
                {
                    "id": f"turn-{number}",
                    "status": "completed",
                    "error": None,
                    "completedAt": int(now) - 1,
                    "items": [
                        {"id": f"message-{number}", "type": "agentMessage", "phase": "final_answer", "text": report}
                    ],
                }
            ],
        }
        raw = json.dumps(event).encode()
        origins[f"synthetic-{number}"] = raw
        reviews.append(
            LocalReviewExpectation(
                capture.candidate,
                canonical_json_sha256([item.model_dump(mode="json") for item in capture.files]),
                capture.mode_manifest_sha256,
                f"synthetic-{number}",
                f"turn-{number}",
                f"message-{number}",
                hashlib.sha256(raw).hexdigest(),
                hashlib.sha256((report + "\n").encode()).hexdigest(),
                int(now) - 1,
            )
        )
    return LocalReviewPolicy("synthetic-operation", plan.digest, now, now + 600, tuple(reviews)), _Host(
        directory, origins
    )


@pytest.fixture(scope="module")
def batch_fixture(tmp_path_factory: pytest.TempPathFactory) -> tuple:
    """Share immutable fixture setup only among pre-execution rejection cases."""
    return _matched(tmp_path_factory.mktemp("reviewed-batch"))


class _Access:
    """Keep capability access observable without masking a mutant with fake failure."""

    def __init__(self, target: object, accesses: list[str]) -> None:
        self.target = target
        self.accesses = accesses

    def __getattr__(self, name: str) -> object:
        self.accesses.append(name)
        return getattr(self.target, name)


def _observe(batch: tuple, accesses: list[str]) -> tuple:
    def wrap(frame: object) -> object:
        return replace(frame, provider=_Access(frame.provider, accesses), judge=_Access(frame.judge, accesses))

    return tuple(MatchedCaseExecution(wrap(pair.baseline), wrap(pair.candidate)) for pair in batch)


@pytest.mark.parametrize(
    "defect,code",
    [
        ("missing", "local_review_policy_required"),
        ("plan", "local_review_plan_mismatch"),
        ("scope", "local_review_policy_required"),
        ("expired", "local_review_operation_expired"),
        ("nan", "local_review_invalid_policy"),
        ("missing_candidate", "local_review_candidate_mismatch"),
        ("duplicate_candidate", "local_review_duplicate_candidate"),
        ("resources", "local_review_resources_mismatch"),
        ("boolean_completion", "local_review_invalid_policy"),
    ],
)
def test_policy_rejections_do_not_access_execution_capabilities(
    batch_fixture: tuple, tmp_path: Path, defect: str, code: str
) -> None:
    plan, calibration, batch, events = batch_fixture
    policy, host = _authority(plan, batch, tmp_path)
    changes = {
        "plan": {"plan_sha256": "0" * 64},
        "scope": {"purpose": "execute"},
        "expired": {"retrieved_at": time.time() - 700, "deadline": time.time() - 101},
        "nan": {"deadline": float("nan")},
        "missing_candidate": {"reviews": policy.reviews[:1]},
        "duplicate_candidate": {"reviews": (policy.reviews[0], policy.reviews[0])},
        "resources": {"reviews": (replace(policy.reviews[0], files_sha256="0" * 64), policy.reviews[1])},
        "boolean_completion": {"reviews": (replace(policy.reviews[0], completed_at=True), policy.reviews[1])},
    }
    selected = None if defect == "missing" else replace(policy, **changes[defect])
    accesses: list[str] = []
    with pytest.raises(ContractError) as error:
        asyncio.run(
            execute_reviewed_matched_lane(
                plan, "local", calibration, _observe(batch, accesses), authority=LocalReviewAuthority(selected, host)
            )
        )
    assert error.value.code == code
    assert not accesses and not events and host.consumptions == 0


@pytest.mark.parametrize(
    "defect,code",
    [
        ("issuer", "local_review_issuer_mismatch"),
        ("turn", "local_review_turn_mismatch"),
        ("message", "local_review_message_mismatch"),
        ("phase", "local_review_not_final"),
        ("report", "local_review_report_mismatch"),
        ("failed", "local_review_incomplete"),
        ("completion", "local_review_completion_mismatch"),
        ("stale", "local_review_stale"),
        ("transport", "local_review_transport_changed"),
        ("malformed", "local_review_admission_failed"),
    ],
)
def test_fabricated_and_stale_origins_reject_the_entire_batch(
    batch_fixture: tuple, tmp_path: Path, defect: str, code: str
) -> None:
    plan, calibration, batch, events = batch_fixture
    policy, host = _authority(plan, batch, tmp_path)
    # Attack the last candidate, so early valid review cannot admit a partial batch.
    expected = policy.reviews[1]
    event = json.loads(host.origins[expected.thread_id])
    changes = {
        "issuer": lambda: event["thread"].update(id="forged"),
        "turn": lambda: event["turns"][0].update(id="forged"),
        "message": lambda: event["turns"][0]["items"][0].update(id="forged"),
        "phase": lambda: event["turns"][0]["items"][0].update(phase="commentary"),
        "report": lambda: event["turns"][0]["items"][0].update(text="forged"),
        "failed": lambda: event["turns"][0].update(status="failed"),
        "completion": lambda: event["turns"][0].update(completedAt=0),
        "stale": lambda: event["turns"][0].update(completedAt=int(time.time()) - 3601),
    }
    if defect in changes:
        changes[defect]()
    raw = b"{" if defect == "malformed" else json.dumps(event).encode()
    if defect == "transport":
        raw += b" "
    host.origins[expected.thread_id] = raw
    if defect != "transport":
        expected = replace(expected, event_sha256=hashlib.sha256(raw).hexdigest())
    if defect == "stale":
        expected = replace(expected, completed_at=event["turns"][0]["completedAt"])
    policy = replace(policy, reviews=(policy.reviews[0], expected))
    accesses: list[str] = []
    with pytest.raises(ContractError) as error:
        asyncio.run(
            execute_reviewed_matched_lane(
                plan, "local", calibration, _observe(batch, accesses), authority=LocalReviewAuthority(policy, host)
            )
        )
    assert error.value.code == code
    assert not accesses and not events and host.consumptions == 0


def test_real_executor_runs_then_restarted_host_refuses_consumed_operation(tmp_path: Path) -> None:
    plan, calibration, batch, events = _matched(tmp_path / "source")
    policy, host = _authority(plan, batch, tmp_path)
    result = asyncio.run(
        execute_reviewed_matched_lane(plan, "local", calibration, batch, authority=LocalReviewAuthority(policy, host))
    )
    assert result.status == "completed" and len(result.pairs) == 20
    assert result.provider_invocation_count == result.judge_invocation_count == 40
    assert events.count("provider") == events.count("dimensional_judge") == 40
    events.clear()
    restarted = _Host(tmp_path, deepcopy(host.origins))
    accesses: list[str] = []
    with pytest.raises(ContractError, match="Trusted local") as error:
        asyncio.run(
            execute_reviewed_matched_lane(
                plan, "local", calibration, _observe(batch, accesses), authority=LocalReviewAuthority(policy, restarted)
            )
        )
    assert error.value.code == "local_review_consumption_rejected"
    assert not accesses and not events


def test_host_side_effect_source_drift_and_uncertain_consumption_fail_closed(tmp_path: Path) -> None:
    plan, calibration, batch, events = _matched(tmp_path / "source")
    policy, host = _authority(plan, batch, tmp_path)
    target = batch[-1].candidate.plugin_context.root / "shared.md"
    original = target.read_bytes()

    class DriftHost(_Host):
        def resolve_review(self, expected: LocalReviewExpectation) -> bytes:
            target.write_text("Changed during host resolution")
            return super().resolve_review(expected)

    accesses: list[str] = []
    with pytest.raises(ContractError) as error:
        asyncio.run(
            execute_reviewed_matched_lane(
                plan,
                "local",
                calibration,
                _observe(batch, accesses),
                authority=LocalReviewAuthority(policy, DriftHost(tmp_path, host.origins)),
            )
        )
    assert error.value.code == "local_review_source_changed" and not accesses and not events
    target.write_bytes(original)

    class UncertainHost(_Host):
        def consume(self, operation_id: str, policy_sha256: str) -> bool:
            super().consume(operation_id, policy_sha256)
            raise OSError("uncertain write completion")

    uncertain = UncertainHost(tmp_path, host.origins)
    with pytest.raises(ContractError) as error:
        asyncio.run(
            execute_reviewed_matched_lane(
                plan, "local", calibration, _observe(batch, accesses), authority=LocalReviewAuthority(policy, uncertain)
            )
        )
    assert error.value.code == "local_review_admission_failed" and not accesses and not events
    with pytest.raises(ContractError) as error:
        asyncio.run(
            execute_reviewed_matched_lane(
                plan, "local", calibration, _observe(batch, accesses), authority=LocalReviewAuthority(policy, host)
            )
        )
    assert error.value.code == "local_review_consumption_rejected" and not accesses and not events


@pytest.mark.parametrize("age,accepted", [(-1.0, False), (3600.0, True), (3600.001, False)])
def test_review_age_boundary_preserves_later_calibration_gate(
    batch_fixture: tuple, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, age: float, accepted: bool
) -> None:
    plan, _calibration, batch, events = batch_fixture
    policy, host = _authority(plan, batch, tmp_path)
    now = float(policy.reviews[0].completed_at) + age
    policy = replace(policy, retrieved_at=now - 1, deadline=now + 599)
    monkeypatch.setattr(service, "time", SimpleNamespace(time=lambda: now))
    accesses: list[str] = []
    operation = execute_reviewed_matched_lane(
        plan, "local", (), _observe(batch, accesses), authority=LocalReviewAuthority(policy, host)
    )
    if accepted:
        result = asyncio.run(operation)
        assert result.status == "blocked" and result.blocker.code == "invalid_matched_execution"
        assert host.consumptions == 1
    else:
        with pytest.raises(ContractError) as error:
            asyncio.run(operation)
        assert error.value.code == "local_review_stale" and host.consumptions == 0
    assert not accesses and not events


def test_source_drift_after_successful_consumption_blocks_execution(tmp_path: Path) -> None:
    plan, calibration, batch, events = _matched(tmp_path / "source")
    policy, host = _authority(plan, batch, tmp_path)
    target = batch[-1].candidate.plugin_context.root / "shared.md"

    class DriftHost(_Host):
        def consume(self, operation_id: str, policy_sha256: str) -> bool:
            accepted = super().consume(operation_id, policy_sha256)
            target.write_text("Changed during successful consumption")
            return accepted

    drifting = DriftHost(tmp_path, host.origins)
    accesses: list[str] = []
    with pytest.raises(ContractError) as error:
        asyncio.run(
            execute_reviewed_matched_lane(
                plan, "local", calibration, _observe(batch, accesses), authority=LocalReviewAuthority(policy, drifting)
            )
        )
    assert error.value.code == "local_review_source_changed"
    assert drifting.consumptions == 1 and not accesses and not events


@pytest.mark.parametrize(
    "failure",
    [
        OSError,
        RuntimeError,
        AttributeError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        RecursionError,
        ContractError,
        ArithmeticError,
    ],
)
def test_host_exception_contract_preserves_zero_access(
    batch_fixture: tuple, tmp_path: Path, failure: type[Exception]
) -> None:
    plan, calibration, batch, events = batch_fixture
    policy, host = _authority(plan, batch, tmp_path)

    class FailingHost(_Host):
        def resolve_review(self, expected: LocalReviewExpectation) -> bytes:
            if failure is ContractError:
                raise ContractError("synthetic_host_blocker", "Synthetic host blocker")
            raise failure("Synthetic host failure")

    accesses: list[str] = []
    expected_error = ArithmeticError if failure is ArithmeticError else ContractError
    with pytest.raises(expected_error) as error:
        asyncio.run(
            execute_reviewed_matched_lane(
                plan,
                "local",
                calibration,
                _observe(batch, accesses),
                authority=LocalReviewAuthority(policy, FailingHost(tmp_path, host.origins)),
            )
        )
    if isinstance(error.value, ContractError):
        expected_code = "synthetic_host_blocker" if failure is ContractError else "local_review_admission_failed"
        assert error.value.code == expected_code
    assert not accesses and not events


@pytest.mark.parametrize("response", [False, None, 1])
def test_consumption_requires_exact_true(batch_fixture: tuple, tmp_path: Path, response: object) -> None:
    plan, calibration, batch, events = batch_fixture
    policy, host = _authority(plan, batch, tmp_path)

    class RefusingHost(_Host):
        def consume(self, operation_id: str, policy_sha256: str) -> object:
            return response

    accesses: list[str] = []
    with pytest.raises(ContractError) as error:
        asyncio.run(
            execute_reviewed_matched_lane(
                plan,
                "local",
                calibration,
                _observe(batch, accesses),
                authority=LocalReviewAuthority(policy, RefusingHost(tmp_path, host.origins)),
            )
        )
    assert error.value.code == "local_review_consumption_rejected" and not accesses and not events
