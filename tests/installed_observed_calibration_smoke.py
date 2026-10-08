"""Installed calibration proof: controlled callbacks, not live model judging."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import skills_sdk
from skills_sdk.evaluation import (
    CalibrationProbeExecution,
    SuppliedTextProviderAdapter,
    execute_scorer_calibration,
    load_selected_case,
)
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.models import CalibrationJudgeVerdict, ObservedCalibrationPlan
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.scorer_quality import ScorerJudgeParameters


def prepare(root: Path) -> None:
    """Build synthetic inputs before entering the installed environment."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from test_observed_calibration import _batch, _host_input

    root.mkdir()
    plan, executions, _ = _batch(root)
    (root / "host-input.json").write_text(json.dumps(_host_input(plan, executions)), encoding="utf-8")


class FixtureJudge:
    """Observe callback invocation without importing repository test helpers."""

    def __init__(self, data: dict[str, object], events: list[str]) -> None:
        self.identity = ProviderIdentityV2.model_validate(data["identity"])
        self.parameters = ScorerJudgeParameters.model_validate(data["parameters"])
        self.verdict = CalibrationJudgeVerdict.model_validate(data["verdict"])
        self.events = events

    async def judge(self, inputs: object) -> object:
        """Return retained fixture verdict through an actually invoked callback."""
        assert "expected_label" not in inputs.__dataclass_fields__
        self.events.append("judge")
        return self.verdict

    async def cleanup(self) -> None:
        """Own no runtime or external resources."""


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
    for accepted in (True, False, True):
        payload = json.loads(json.dumps(original))
        if not accepted:
            payload["executions"][1]["safety_evidence"] = None
        path.write_text(json.dumps(payload), encoding="utf-8")
        code, receipt = _cli(root)
        assert code == (0 if accepted else 2) and receipt["status"] == ("pass" if accepted else "blocked")
        assert receipt["judge_invocation_count"] == (2 if accepted else 0)
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
