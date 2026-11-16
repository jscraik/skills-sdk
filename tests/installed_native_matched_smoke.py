"""Installed native dimensional and supplied-pair proof with inert callbacks."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import skills_sdk
from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import (
    CalibrationProbeExecution,
    SuppliedTextProviderAdapter,
    assess_native_matched_pair,
    execute_native_matched_calibration,
    load_selected_case,
)
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.models import MatchedVariantJudgment, NativeCalibrationPlan, NativeMatchedComparisonPlan
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest


def prepare(root: Path) -> None:
    """Prepare synthetic source and public artifacts with the source checkout."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from test_matched_comparison import _plan
    from test_native_matched_calibration import _native_dimensions, _native_pair, _pair_judgment

    root.mkdir()
    (root / "calibration").mkdir()
    plan, frames, _events = _native_dimensions(root / "calibration")
    rubric = _plan().rubric
    observed = asyncio.run(execute_native_matched_calibration(plan, rubric, frames))
    assert observed.status == "pass"
    rows = [
        {
            "request": frame.request.model_dump(mode="json"),
            "payload": frame.inputs.payload,
            "safety": frame.inputs.safety_evidence.model_dump(mode="json"),
            "descriptor": frame.provider.descriptor.model_dump(mode="json"),
            "text": frame.provider.text,
            "judgment": judgment.model_dump(mode="json"),
        }
        for frame, judgment in zip(frames, observed.judgments, strict=True)
    ]
    paired, bundles = _native_pair(root / "pair")
    payload = {
        "plan": plan.model_dump(mode="json"),
        "rubric": rubric.model_dump(mode="json"),
        "rows": rows,
        "pair_plan": paired.model_dump(mode="json"),
        "bundles": [bundle.model_dump(mode="json") for bundle in bundles],
        "left": _pair_judgment(paired, "baseline", 2.5).model_dump(mode="json"),
        "right": _pair_judgment(paired, "candidate", 4.0).model_dump(mode="json"),
    }
    (root / "native-matched.json").write_text(json.dumps(payload), encoding="utf-8")


@dataclass
class FixtureJudge:
    """Supply retained fixture dimensions, never launch a model or tool."""

    identity: object
    parameters: object
    judgment: object
    events: list[str]

    async def judge(self, inputs: object) -> object:
        assert inputs.selected.output_sha256 == self.judgment.evidence.output_sha256
        assert "expected_label" not in inputs.__dataclass_fields__
        self.events.append("judge")
        return self.judgment

    async def cleanup(self) -> None:
        self.events.append("cleanup")


@dataclass
class FixtureProvider:
    """Record provider dispatch as well as judge dispatch in installed proof."""

    delegate: object
    events: list[str]

    @property
    def descriptor(self) -> object:
        return self.delegate.descriptor

    async def complete(self, request: object, payload: object) -> object:
        self.events.append("provider")
        return await self.delegate.complete(request, payload)

    async def cleanup(self) -> None:
        self.events.append("provider_cleanup")
        await self.delegate.cleanup()


def _frames(root: Path, data: dict, events: list[str]) -> tuple[CalibrationProbeExecution, ...]:
    plan = NativeCalibrationPlan.model_validate(data["plan"])
    frames = []
    for row in data["rows"]:
        request = ProviderExecutionRequest.model_validate(row["request"])
        definition = load_selected_case(
            root / "calibration/simplify",
            source_revision=request.candidate.source_revision,
            case_id=request.case_id,
            mode="release",
        )
        frames.append(
            CalibrationProbeExecution(
                definition,
                request,
                SelectedCaseExecutionInput(row["payload"], row["safety"]),
                FixtureProvider(
                    SuppliedTextProviderAdapter(
                        TextProviderAdapterDescriptor.model_validate(row["descriptor"]),
                        row["text"],
                        ("evidence/provider-result.json",),
                    ),
                    events,
                ),
                FixtureJudge(
                    plan.judge, plan.parameters, MatchedVariantJudgment.model_validate(row["judgment"]), events
                ),
            )
        )
    return tuple(frames)


def _check_private_mcp_names(data: dict) -> None:
    """Reject correctly bound credential-shaped keys before retaining a plan."""
    raw = json.loads(json.dumps(data["pair_plan"]))
    lane = raw["lanes"][1]
    name = "sk-fixture-not-a-secret"
    lane["judge_parameters"]["disabled_mcp_servers"] = [name]
    lane["judge"]["adapter_version_or_digest"] = canonical_json_sha256(
        {
            "settings": {key: value for key, value in lane["judge_parameters"].items() if key != "schema_version"},
            "rubric_sha256": canonical_json_sha256(raw["rubric"]),
        }
    )
    rejected = assess_native_matched_pair(raw, "local", tuple(data["bundles"]), {}, {})
    assert rejected.status == "blocked" and rejected.plan is None
    assert name not in rejected.model_dump_json()
    try:
        SchemaRegistry().validate("native-matched-comparison-plan.v1", raw)
    except ContractError:
        pass
    else:
        raise AssertionError("installed schema semantics accepted a non-public MCP identity")


def check(root: Path) -> None:
    """Prove installed API/schema rejection, fresh recovery and consumer joins."""
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    assert not any(name.startswith("test_") for name in sys.modules)
    data = json.loads((root / "native-matched.json").read_text())
    _check_private_mcp_names(data)
    events: list[str] = []
    frames = _frames(root, data, events)
    frames[-1].judge.parameters = frames[-1].judge.parameters.model_copy(update={"timeout_seconds": 31})
    rejected = asyncio.run(execute_native_matched_calibration(data["plan"], data["rubric"], frames))
    assert rejected.status == "blocked" and not events
    accepted = asyncio.run(
        execute_native_matched_calibration(data["plan"], data["rubric"], _frames(root, data, events))
    )
    assert accepted.status == "pass" and len(accepted.judgments) == events.count("judge") == 6
    assert events.count("provider") == events.count("provider_cleanup") == events.count("cleanup") == 6
    plan = NativeMatchedComparisonPlan.model_validate(data["pair_plan"])
    bundles = tuple(data["bundles"])
    assert assess_native_matched_pair(plan, "local", bundles[::-1], data["left"], data["right"]).status == "blocked"
    result = assess_native_matched_pair(plan, "local", bundles, data["left"], data["right"])
    assert result.status == "assessed" and result.decision == "candidate"
    assert not result.execution_performed and not result.promotion_authorized
    for artifact in (accepted, plan, result.calibrations[0], result):
        SchemaRegistry().validate(artifact.schema_version.replace("/", "."), artifact.model_dump(mode="json"))
    print("installed native dimensional producer and supplied-pair consumer: pass; inert callbacks only")


if __name__ == "__main__":
    operation, directory = sys.argv[1:]
    if operation == "--prepare":
        prepare(Path(directory).resolve())
    elif operation == "--check":
        check(Path(directory).resolve())
    else:
        raise SystemExit("expected --prepare or --check")
