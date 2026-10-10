"""Installed calibration proof: controlled callbacks, not live model judging."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections import UserDict, UserList
from dataclasses import replace
from pathlib import Path

from pydantic import ValidationError, model_serializer

import skills_sdk
from skills_sdk.evaluation import (
    CalibrationProbeExecution,
    CalibrationTrialAdapters,
    SuppliedTextProviderAdapter,
    execute_matched_calibration,
    execute_scorer_calibration,
    load_selected_case,
)
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.models import CalibrationJudgeVerdict, ObservedCalibrationPlan
from skills_sdk.models.matched_comparison import MatchedComparisonRubric, MatchedVariantJudgment
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.scorer_quality import ScorerJudgeParameters


def prepare(root: Path) -> None:
    """Build synthetic inputs before entering the installed environment."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from test_matched_calibration import _dimensions
    from test_matched_comparison import _plan
    from test_matched_offline_cli import _variant
    from test_observed_calibration import _batch, _host_input

    root.mkdir()
    plan, executions, _ = _batch(root)
    (root / "host-input.json").write_text(json.dumps(_host_input(plan, executions)), encoding="utf-8")
    (root / "dimensional").mkdir()
    dimensional, frames, _ = _dimensions(root / "dimensional", trials=2)
    rubric = _plan().rubric
    (root / "dimensional.json").write_text(
        json.dumps(
            {
                "plan": dimensional.model_dump(mode="json"),
                "rubric": rubric.model_dump(mode="json"),
                "executions": [_variant(item, rubric) for item in frames],
            }
        ),
        encoding="utf-8",
    )


class FixtureJudge:
    """Observe callback invocation without importing repository test helpers."""

    def __init__(self, data: dict[str, object], events: list[str]) -> None:
        """Parse the numeric fixture and initialize callback and lifecycle tracking."""
        self.identity = ProviderIdentityV2.model_validate(data["identity"])
        self.parameters = ScorerJudgeParameters.model_validate(data["parameters"])
        self.verdict = CalibrationJudgeVerdict.model_validate(data["verdict"])
        self.events = events
        self.single_use = False
        self.closed = False

    async def judge(self, inputs: object) -> object:
        """Return retained fixture verdict through an actually invoked callback."""
        assert "expected_label" not in inputs.__dataclass_fields__
        assert not (self.single_use and self.closed)
        self.events.append("judge")
        return self.verdict

    async def cleanup(self) -> None:
        """Close the controlled capability when single-use proof is selected."""
        if self.single_use:
            assert not self.closed
            self.closed = True
            self.events.append("judge_closed")


class ClosingProvider:
    """Fail if a closed installed provider capability is invoked twice."""

    def __init__(self, delegate: SuppliedTextProviderAdapter, events: list[str]) -> None:
        """Wrap a supplied provider with shared events and an initially open state."""
        self.delegate, self.events = delegate, events
        self.descriptor = delegate.descriptor
        self.closed = False

    async def complete(self, request: object, payload: object) -> object:
        """Reject calls after cleanup and record each delegated completion."""
        assert not self.closed
        self.events.append("provider")
        return await self.delegate.complete(request, payload)

    async def cleanup(self) -> None:
        """Close the provider once, record the event and clean up its delegate."""
        assert not self.closed
        self.closed = True
        self.events.append("provider_closed")
        await self.delegate.cleanup()


class DimensionalFixtureJudge:
    """Single-use dimensional capability for installed held-out proof."""

    def __init__(self, raw: dict[str, object], events: list[str]) -> None:
        """Parse a dimensional fixture and initialize its single-use lifecycle."""
        self.identity = ProviderIdentityV2.model_validate(raw["identity"])
        self.parameters = ScorerJudgeParameters.model_validate(raw["parameters"])
        self.judgment = MatchedVariantJudgment.model_validate(raw["judgment"])
        self.events, self.closed = events, False

    async def judge(self, inputs: object) -> object:
        """Return the fixture judgment only while open and without held-out labels."""
        assert not self.closed and "expected_label" not in inputs.__dataclass_fields__
        self.events.append("judge")
        return self.judgment

    async def cleanup(self) -> None:
        """Close the judge once and record its cleanup event."""
        assert not self.closed
        self.closed = True
        self.events.append("judge_closed")


def _dimensional(root: Path) -> None:
    """Verify installed dimensional trials reject missing pairs and accept fresh ones."""
    data = json.loads((root / "dimensional.json").read_text())
    plan = ObservedCalibrationPlan.model_validate(data["plan"])
    rubric = MatchedComparisonRubric.model_validate(data["rubric"])
    events: list[str] = []
    frames = []
    for item in data["executions"]:
        pairs = tuple(
            CalibrationTrialAdapters(
                ClosingProvider(
                    SuppliedTextProviderAdapter(
                        TextProviderAdapterDescriptor.model_validate(item["provider"]["descriptor"]),
                        item["provider"]["output_text"],
                        tuple(item["provider"]["evidence_refs"]),
                    ),
                    events,
                ),
                DimensionalFixtureJudge(item["judge"], events),
            )
            for _ in range(2)
        )
        frames.append(
            CalibrationProbeExecution(
                load_selected_case(
                    Path(item["package_root"]),
                    source_revision=item["source_revision"],
                    case_id=item["case_id"],
                    mode="release",
                ),
                ProviderExecutionRequest.model_validate(item["request"]),
                SelectedCaseExecutionInput(item["input_payload"], item["safety_evidence"]),
                pairs[0].provider,
                pairs[0].judge,
                pairs[1:],
            )
        )
    valid = tuple(frames)
    invalid = (replace(valid[0], trial_adapters=()), *valid[1:])
    rejected = asyncio.run(execute_matched_calibration(plan, rubric, invalid))
    assert rejected.status == "blocked" and events == []
    accepted = asyncio.run(execute_matched_calibration(plan, rubric, valid))
    assert accepted.status == "pass" and len(accepted.judgments) == 12
    assert accepted.calibration.judge_invocation_count == 12
    assert events.count("provider_closed") == events.count("judge_closed") == 12
    assert not accepted.promotion_authorized and not accepted.external_authenticity_verified
    print("installed six-probe two-trial stateful dimensional calibration rejection/recovery: pass")


def _executions(root: Path, data: dict[str, object], events: list[str]) -> tuple[CalibrationProbeExecution, ...]:
    revision = data["plan"]["candidate"]["source_revision"]
    return tuple(
        CalibrationProbeExecution(
            load_selected_case(root / "simplify", source_revision=revision, case_id=item["case_id"], mode=item["mode"]),
            ProviderExecutionRequest.model_validate(item["request"]),
            SelectedCaseExecutionInput(item["input_payload"], item["safety_evidence"]),
            SuppliedTextProviderAdapter(
                TextProviderAdapterDescriptor.model_validate(item["provider"]["descriptor"]),
                item["provider"]["output_text"],
                tuple(item["provider"]["evidence_refs"]),
            ),
            FixtureJudge(item["judge"], events),
        )
        for item in data["executions"]
    )


def _api(root: Path, original: dict[str, object]) -> None:
    events: list[str] = []
    plan = ObservedCalibrationPlan.model_validate(original["plan"])
    valid = _executions(root, original, events)
    accepted = asyncio.run(execute_scorer_calibration(plan, valid))
    assert accepted.status == "pass" and events == ["judge", "judge"]
    assert accepted.plan.candidate == plan.candidate and not accepted.external_authenticity_verified
    events.clear()
    invalid = json.loads(json.dumps(original))
    invalid["executions"][1]["request"]["case_id"] = "other-case"
    rejected = asyncio.run(execute_scorer_calibration(plan, _executions(root, invalid, events)))
    assert rejected.status == "blocked" and rejected.judge_invocation_count == 0 and events == []
    assert asyncio.run(execute_scorer_calibration(plan, valid)).status == "pass"
    events.clear()
    _ingress(plan, valid, events)


def _repeated_api(root: Path, original: dict[str, object]) -> None:
    """Reject reused capabilities before execution, then run fresh stateful pairs."""
    data = json.loads(json.dumps(original))
    data["plan"]["parameters"]["trial_count"] = 2
    for item in data["executions"]:
        item["judge"]["parameters"]["trial_count"] = 2
    plan = ObservedCalibrationPlan.model_validate(data["plan"])
    events: list[str] = []
    batches = tuple(_executions(root, data, events) for _ in range(2))
    prepared = []
    for first, second in zip(*batches, strict=True):
        first.judge.single_use = second.judge.single_use = True
        prepared.append(
            replace(
                first,
                provider=ClosingProvider(first.provider, events),
                trial_adapters=(CalibrationTrialAdapters(ClosingProvider(second.provider, events), second.judge),),
            )
        )
    valid = tuple(prepared)
    invalid = (
        replace(valid[0], trial_adapters=(CalibrationTrialAdapters(valid[0].provider, valid[0].judge),)),
        *valid[1:],
    )
    rejected = asyncio.run(execute_scorer_calibration(plan, invalid))
    assert rejected.status == "blocked" and rejected.blocker.code == "calibration_capability_reuse"
    assert rejected.judge_invocation_count == 0 and events == []
    accepted = asyncio.run(execute_scorer_calibration(plan, valid))
    assert accepted.status == "pass" and accepted.judge_invocation_count == 4
    assert [row.trial_index for row in accepted.results] == [0, 1, 0, 1]
    assert events.count("provider_closed") == events.count("judge_closed") == 4
    assert not accepted.promotion_authorized and not accepted.external_authenticity_verified
    print("installed stateful repeated calibration rejection/recovery: pass")


def _ingress(plan: ObservedCalibrationPlan, valid: tuple[CalibrationProbeExecution, ...], events: list[str]) -> None:
    """Reject caller serializers, direct subclasses and bytes in the installed API."""
    calls: list[str] = []

    class CallerProvider(ProviderIdentityV2):
        @model_serializer(mode="plain")
        def mask_members(self) -> dict[str, object]:
            calls.append("serializer")
            return plan.judge.model_dump(mode="python")

    forged = CallerProvider.model_construct(**plan.judge.__dict__).model_copy(update={"provider_kind": "bogus"})
    malformed = {**plan.model_dump(mode="json"), "judge": forged}
    blocked = asyncio.run(execute_scorer_calibration(malformed, valid))
    assert blocked.blocker.code == "invalid_calibration_input" and blocked.judge_invocation_count == 0
    assert calls == [] and events == []
    view_input = {**plan.model_dump(mode="json"), "judge": UserDict({"provider": forged})}
    blocked = asyncio.run(execute_scorer_calibration(view_input, valid))
    assert blocked.blocker.code == "invalid_calibration_input" and blocked.judge_invocation_count == 0
    assert calls == [] and events == []
    verdict = valid[0].judge.verdict
    for field in ("provider", "judge"):
        identity = getattr(verdict.evidence, field)
        evidence = {
            **verdict.evidence.model_dump(mode="json"),
            field: identity.model_copy(update={"provider_id": b"synthetic-provider"}),
        }
        try:
            CalibrationJudgeVerdict.model_validate({"evidence": evidence, "score": verdict.score})
        except ValidationError:
            pass
        else:
            raise AssertionError("installed mixed typed bytes must reject before coercion")
    for field in ("evidence_refs", "satisfied_assertion_ids"):
        member = getattr(verdict.evidence, field)[0].encode()
        for container in ({member}, UserList([member]), iter([member])):
            evidence = {**verdict.evidence.model_dump(mode="json"), field: container}
            try:
                CalibrationJudgeVerdict.model_validate({"evidence": evidence, "score": verdict.score})
            except ValidationError:
                pass
            else:
                raise AssertionError("installed unsupported containers must reject before coercion")

    class CallerVerdict(CalibrationJudgeVerdict):
        """No subclass may lose its identity before the wrap validator."""

    valid[0].judge.verdict = CallerVerdict.model_construct(**verdict.__dict__)
    blocked = asyncio.run(execute_scorer_calibration(plan, valid))
    assert blocked.status == "blocked" and blocked.judge_invocation_count == 1 and blocked.results == ()
    valid[0].judge.verdict = verdict
    assert asyncio.run(execute_scorer_calibration(plan, valid)).status == "pass"
    print("installed calibration raw/typed serializer, byte, container and subclass rejection/recovery: pass")


def _cli(root: Path) -> tuple[int, dict[str, object]]:
    executable = Path(sys.executable).with_name("skills-sdk.exe" if sys.platform == "win32" else "skills-sdk")
    result = subprocess.run(
        [
            str(executable),
            "eval",
            "observed-calibration",
            str(root / "simplify"),
            "--source-revision",
            "1" * 40,
            "--host-input",
            str(root / "host-input.json"),
            "--adapter-mode",
            "supplied-offline",
            "--json",
            "--robot",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert not result.stderr, result.stderr
    return result.returncode, json.loads(result.stdout)


def check(root: Path) -> None:
    """Exercise installed-only API and CLI acceptance, rejection and recovery."""
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    assert "pytest" not in sys.modules
    path = root / "host-input.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    _api(root, original)
    _repeated_api(root, original)
    _dimensional(root)
    for accepted in (True, False, True):
        payload = json.loads(json.dumps(original))
        payload["plan"]["parameters"]["trial_count"] = 2
        for item in payload["executions"]:
            item["judge"]["parameters"]["trial_count"] = 2
        if not accepted:
            payload["executions"][1]["safety_evidence"] = None
        path.write_text(json.dumps(payload), encoding="utf-8")
        code, receipt = _cli(root)
        assert code == (0 if accepted else 2) and receipt["status"] == ("pass" if accepted else "blocked")
        assert receipt["judge_invocation_count"] == (4 if accepted else 0)
        assert receipt["promotion_authorized"] is False and receipt["external_authenticity_verified"] is False
    assert not any("agent_skills" in name or "skills_foundry" in name for name in sys.modules)
    print("installed observed calibration API/CLI accept, reject and recovery: pass (controlled offline only)")


if __name__ == "__main__":
    mode, directory = sys.argv[1:]
    if mode == "--prepare":
        prepare(Path(directory).resolve())
    elif mode == "--check":
        check(Path(directory).resolve())
    else:
        raise ValueError("select --prepare or --check")
