"""Installed matched workflow proof using synthetic, supplied-offline fixtures."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import model_serializer

import skills_sdk
from skills_sdk import evaluation, models
from skills_sdk.core.schema_registry import SchemaRegistry


def prepare(root: Path) -> None:
    """Prepare safe fixtures before checks run in the separate wheel environment."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from test_matched_calibration import _dimensions
    from test_matched_comparison import _plan
    from test_matched_execution import _matched
    from test_matched_handoff import _journey
    from test_matched_offline_cli import _pairs, _variant

    root.mkdir()
    for name in ("local", "calibration", "cloud"):
        (root / name).mkdir()
    plan, calibrations, batch, _ = _matched(root / "local", child_count=2)
    local = {
        "plan": plan.model_dump(mode="json"),
        "calibrations": [item.model_dump(mode="json") for item in calibrations],
        "executions": _pairs(batch, plan.rubric),
    }
    calibration, probes, _ = _dimensions(root / "calibration")
    numeric = {
        "plan": calibration.model_dump(mode="json"),
        "rubric": _plan().rubric.model_dump(mode="json"),
        "executions": [_variant(item, _plan().rubric) for item in probes],
    }
    local_receipt, cloud_plan, cloud_calibrations, cloud_batch, _ = _journey(root / "cloud")
    cloud = {
        "handoff": evaluation.prepare_matched_cloud_handoff(local_receipt, cloud_plan).model_dump(mode="json"),
        "calibrations": [item.model_dump(mode="json") for item in cloud_calibrations],
        "executions": _pairs(cloud_batch, cloud_plan.rubric),
    }
    for name, payload in (("local", local), ("calibration", numeric), ("cloud", cloud)):
        (root / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")


@dataclass
class FixtureJudge:
    """Explicit fixture capability with no external resources or discovery."""

    identity: object
    parameters: object
    judgment: object

    async def judge(self, inputs: object) -> object:
        """Observe the callback without giving it held-out labels."""
        assert "expected_label" not in inputs.__dataclass_fields__
        return self.judgment

    async def cleanup(self) -> None:
        """Own no external resources."""


@dataclass
class FixtureProvider:
    """Supply text through the public adapter with explicit frozen settings."""

    delegate: object
    parameters: object

    @property
    def descriptor(self) -> object:
        return self.delegate.descriptor

    async def complete(self, request: object, payload: object) -> object:
        return await self.delegate.complete(request, payload)

    async def cleanup(self) -> None:
        await self.delegate.cleanup()


def _variant(raw: dict[str, object]) -> object:
    from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
    from skills_sdk.models.provider_call import TextProviderAdapterDescriptor

    provider, judge = raw["provider"], raw["judge"]
    context = raw["plugin_context"]
    provider_parameters = models.ScorerJudgeParameters.model_validate(provider["parameters"])
    judge_parameters = models.ScorerJudgeParameters.model_validate(judge["parameters"])

    def adapters() -> object:
        return evaluation.MatchedTrialAdapters(
            FixtureProvider(
                evaluation.SuppliedTextProviderAdapter(
                    TextProviderAdapterDescriptor.model_validate(provider["descriptor"]),
                    provider["output_text"],
                    tuple(provider["evidence_refs"]),
                ),
                provider_parameters,
            ),
            FixtureJudge(
                models.ProviderIdentityV2.model_validate(judge["identity"]),
                judge_parameters,
                models.MatchedVariantJudgment.model_validate(judge["judgment"]),
            ),
        )

    first = adapters()
    return evaluation.MatchedVariantExecution(
        evaluation.load_selected_case(
            Path(raw["package_root"]), source_revision=raw["source_revision"], case_id=raw["case_id"], mode="release"
        ),
        models.ProviderExecutionRequest.model_validate(raw["request"]),
        SelectedCaseExecutionInput(raw["input_payload"], raw["safety_evidence"]),
        first.provider,
        first.judge,
        evaluation.PluginExecutionContext(
            root=Path(context["root"]),
            validation=models.PluginPackageValidation.model_validate(context["validation"]),
            driver_skill_path=context["driver_skill_path"],
            selected_skill_paths=tuple(context["selected_skill_paths"]),
            reference_paths=tuple(context["reference_paths"]),
            policy=models.PluginValidationPolicy.model_validate(context["policy"]),
            safety_evidence=models.PluginPreExecutionSafetyEvidence.model_validate(context["safety_evidence"]),
        ),
        tuple(adapters() for _ in range(provider_parameters.trial_count - 1)),
    )


def _api(payload: dict[str, object]) -> None:
    batch = tuple(
        evaluation.MatchedCaseExecution(_variant(item["baseline"]), _variant(item["candidate"]))
        for item in payload["executions"]
    )
    calibrations = tuple(payload["calibrations"])
    for frames, expected in ((batch, "completed"), (batch[:-1], "blocked"), (batch, "completed")):
        receipt = asyncio.run(evaluation.execute_matched_lane(payload["plan"], "local", calibrations, frames))
        assert receipt.status == expected
        assert receipt.provider_invocation_count == (40 if expected == "completed" else 0)
        SchemaRegistry().validate("matched-execution.v1", receipt.model_dump(mode="json"))
        if expected == "completed":
            pair = receipt.comparison(0)
            assessed = evaluation.assess_matched_pair(receipt.plan, "local", pair.baseline, pair.candidate)
            assert assessed == pair and not assessed.execution_performed


def _rejected(model: type, value: object) -> None:
    try:
        model.model_validate(value)
    except ValueError:
        return
    raise AssertionError("installed matched ingress accepted noncanonical input")


def _ingress(payload: dict[str, object]) -> None:
    """Prove canonical recovery without caller serializers or byte coercion."""
    plan = models.MatchedComparisonPlan.model_validate(payload["plan"])
    lane = plan.lanes[0]
    calls: list[str] = []

    class HiddenProvider(models.ProviderIdentityV2):
        @model_serializer(mode="plain")
        def disguise(self) -> dict[str, object]:
            calls.append("serializer")
            return lane.judge.model_dump(mode="python")

    hidden = HiddenProvider.model_construct(**dict(lane.judge.__dict__, provider_kind="bogus"))
    _rejected(models.MatchedLaneSpec, dict(lane.__dict__, judge=hidden))
    _rejected(models.MatchedLaneSpec, lane.model_copy(update={"unknown": True}))
    dimension = models.MatchedDimensionJudgment(
        dimension_id="success", score=3.0, rationale="Evidence retained.", evidence_refs=("evidence/judgment.json",)
    )
    for refs in ([b"evidence/judgment.json"], {b"evidence/judgment.json"}, iter([b"evidence/judgment.json"])):
        _rejected(models.MatchedDimensionJudgment, dict(dimension.__dict__, evidence_refs=refs))
    assert not calls
    assert models.MatchedDimensionJudgment.model_validate(dimension) == dimension
    assert models.MatchedComparisonPlan.model_validate(plan) == plan
    SchemaRegistry().validate("matched-comparison-plan.v1", plan.model_dump(mode="json"))


def _cli(root: Path, command: str, payload: object, schema: str, expected: int = 0) -> dict[str, object]:
    source = root / "host-input.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    executable = Path(sys.executable).with_name("skills-sdk.exe" if sys.platform == "win32" else "skills-sdk")
    result = subprocess.run(
        [
            str(executable),
            "eval",
            command,
            "--input",
            str(source),
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
    assert result.returncode == expected and not result.stderr, (result.returncode, result.stdout, result.stderr)
    receipt = json.loads(result.stdout)
    SchemaRegistry().validate(schema, receipt)
    assert receipt["promotion_authorized"] is False
    return receipt


def _failure(payload: dict[str, object]) -> dict[str, object]:
    changed = json.loads(json.dumps(payload))
    candidate = changed["executions"][0]["candidate"]
    candidate["provider"]["output_text"] = "behavior preserved; rm -rf"
    candidate["judge"]["judgment"]["evidence"]["output_sha256"] = hashlib.sha256(
        b"behavior preserved; rm -rf"
    ).hexdigest()
    return changed


def _provider_mode(payload: dict[str, object], mode: str) -> dict[str, object]:
    """Select a protocol in fixture JSON without changing source or evidence."""
    changed = json.loads(json.dumps(payload))
    for execution in changed["executions"]:
        variants = execution.values() if "baseline" in execution else (execution,)
        for variant in variants:
            variant["provider"]["descriptor"]["mode"] = mode
    return changed


def _cli_workflow(root: Path, local: dict[str, object], numeric: object, cloud: object) -> None:
    """Prove all five installed routes for the selected fixture protocol."""
    for payload, code in (
        (local, 0),
        (dict(local, executions=local["executions"][:-1]), 2),
        (_provider_mode(local, "unsupported"), 2),
        (local, 0),
    ):
        result = _cli(root, "matched-local", payload, "matched-execution.v1", code)
        assert result["provider_invocation_count"] == (40 if code == 0 else 0)
    for payload, code in ((numeric, 0), (dict(numeric, extra=True), 2), (numeric, 0)):
        result = _cli(root, "matched-calibration", payload, "matched-calibration.v1", code)
        assert result["status"] == ("pass" if code == 0 else "blocked")
    for command, schema, payload in (
        ("matched-local", "matched-regression.v1", local),
        ("matched-cloud", "matched-cloud-regression.v1", cloud),
    ):
        initial_schema = "matched-execution.v1" if command == "matched-local" else "matched-cloud-execution.v1"
        initial = _cli(root, command, _failure(payload), initial_schema)
        plan = payload.get("plan") or payload["handoff"]["cloud_plan"]
        recovery = {
            "initial": initial,
            "assignments": [{"case_id": "case-0", "owner": "SDK maintainer"}],
            "plan": plan,
            "calibrations": payload["calibrations"],
            "executions": payload["executions"],
        }
        route = "matched-regression" if command == "matched-local" else "matched-cloud-regression"
        _cli(root, route, dict(recovery, assignments=[]), schema, 2)
        result = _cli(root, route, recovery, schema)
        assert result["status"] == "closed" and result["initial"] == initial


def check(root: Path) -> None:
    """Use installed public API and CLI with supplied-offline fixtures."""
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    assert "pytest" not in sys.modules
    local = json.loads((root / "local.json").read_text())
    numeric = json.loads((root / "calibration.json").read_text())
    cloud = json.loads((root / "cloud.json").read_text())
    _ingress(local)
    _api(local)
    for mode in ("complete", "stream"):
        _cli_workflow(root, _provider_mode(local, mode), _provider_mode(numeric, mode), _provider_mode(cloud, mode))
    assert not any("agent_skills" in name or "skills_foundry" in name for name in sys.modules)
    print(
        "installed matched API complete and CLI complete/stream: "
        "acceptance, rejection and recovery pass (supplied-offline)"
    )


if __name__ == "__main__":
    mode, directory = sys.argv[1:]
    if mode == "--prepare":
        prepare(Path(directory).resolve())
    elif mode == "--check":
        check(Path(directory).resolve())
    else:
        raise ValueError("select --prepare or --check")
