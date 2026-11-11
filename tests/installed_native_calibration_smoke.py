"""Installed native calibration using controlled executables and synthetic source."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import skills_sdk
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import (
    CalibrationProbeExecution,
    SuppliedTextProviderAdapter,
    execute_native_calibration,
    load_selected_case,
)
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.models import NativeCalibrationPlan
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.providers.codex_judge import CodexCalibrationJudgeAdapter, CodexJudgeAdapter, CodexJudgeSettings


def prepare(root: Path) -> None:
    """Serialize fixtures before entering the isolated wheel environment."""
    root = root.resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from test_native_calibration import _native_batch

    root.mkdir()
    plan, executions, _events = _native_batch(root)
    rows = [
        {
            "request": item.request.model_dump(mode="json"),
            "payload": item.inputs.payload,
            "safety": item.inputs.safety_evidence.model_dump(mode="json"),
            "descriptor": item.provider.descriptor.model_dump(mode="json"),
            "text": item.provider.text,
            "executable": str(root / ("judge" + str(index)) / "codex-fixture"),
        }
        for index, item in enumerate(executions)
    ]
    (root / "native.json").write_text(json.dumps({"plan": plan.model_dump(mode="json"), "rows": rows}))


def _executions(root: Path, data: dict, retained: list[str]) -> tuple[CalibrationProbeExecution, ...]:
    """Allocate fresh installed adapters without importing test helpers."""
    plan = NativeCalibrationPlan.model_validate(data["plan"])
    controls = plan.parameters
    settings = CodexJudgeSettings(
        controls.model,
        controls.cli_version,
        controls.disabled_mcp_servers,
        reasoning_effort=controls.reasoning_effort,
        timeout_seconds=controls.timeout_seconds,
    )

    async def retain(ref: str, payload: bytes) -> None:
        assert ref == "judge-results/" + hashlib.sha256(payload).hexdigest()
        retained.append(ref)

    frames = []
    for row in data["rows"]:
        request = ProviderExecutionRequest.model_validate(row["request"])
        definition = load_selected_case(
            root / "simplify",
            source_revision=request.candidate.source_revision,
            case_id=request.case_id,
            mode="release",
        )
        executable = Path(row["executable"])
        frames.append(
            CalibrationProbeExecution(
                definition,
                request,
                SelectedCaseExecutionInput(row["payload"], row["safety"]),
                SuppliedTextProviderAdapter(
                    TextProviderAdapterDescriptor.model_validate(row["descriptor"]),
                    row["text"],
                    ("evidence/provider-result.json",),
                ),
                CodexCalibrationJudgeAdapter(
                    CodexJudgeAdapter(
                        executable,
                        executable.parent,
                        settings,
                        "Rubric",
                        retain_result=retain,
                    )
                ),
            )
        )
    return tuple(frames)


def check(root: Path) -> None:
    """Prove installed acceptance, rejection before dispatch and fresh recovery."""
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    assert not any(name.startswith("test_") for name in sys.modules)
    data = json.loads((root / "native.json").read_text())
    plan = NativeCalibrationPlan.model_validate(data["plan"])
    registry = SchemaRegistry()
    registry.validate("native-calibration-plan.v1", data["plan"])
    retained: list[str] = []
    forged = plan.model_copy(update={"parameters": plan.parameters.model_copy(update={"temperature": 0.0})})
    rejected = asyncio.run(execute_native_calibration(forged, _executions(root, data, retained)))
    assert rejected.status == "blocked" and rejected.judge_invocation_count == 0 and retained == []
    accepted = asyncio.run(execute_native_calibration(plan, _executions(root, data, retained)))
    assert accepted.status == "pass" and accepted.judge_invocation_count == 2 and len(retained) == 2
    assert [item.score for item in accepted.results] == [0.9, 0.1]
    assert not accepted.external_authenticity_verified and not accepted.promotion_authorized
    registry.validate("native-calibration.v1", accepted.model_dump(mode="json"))
    print("installed native calibration acceptance/rejection/fresh recovery: pass (controlled executable)")


if __name__ == "__main__":
    operation, directory = sys.argv[1:]
    if operation == "--prepare":
        prepare(Path(directory))
    elif operation == "--check":
        check(Path(directory))
    else:
        raise SystemExit("expected --prepare or --check")
