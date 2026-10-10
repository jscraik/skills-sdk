"""Installed matched workflow proof using synthetic, supplied-offline fixtures."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from pydantic import model_serializer

import skills_sdk
from skills_sdk import evaluation, models
from skills_sdk.core.digests import canonical_json_sha256
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
    calibration, probes, _ = _dimensions(root / "calibration", trials=2)
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
    invalid = _invalid_reference(payload, "SKILL.md")
    invalid_batch = tuple(
        evaluation.MatchedCaseExecution(_variant(item["baseline"]), _variant(item["candidate"]))
        for item in invalid["executions"]
    )
    for plan, frames, expected in (
        (payload["plan"], batch, "completed"),
        (payload["plan"], batch[:-1], "blocked"),
        (invalid["plan"], invalid_batch, "blocked"),
        (payload["plan"], batch, "completed"),
    ):
        receipt = asyncio.run(evaluation.execute_matched_lane(plan, "local", calibrations, frames))
        assert receipt.status == expected
        assert receipt.provider_invocation_count == (40 if expected == "completed" else 0)
        SchemaRegistry().validate("matched-execution.v1", receipt.model_dump(mode="json"))
        if expected == "completed":
            for offset in (1, 2):
                extra = receipt.model_dump(mode="json")
                extra["provider_invocation_count"] += offset
                _rejected(models.MatchedExecutionReceipt, extra)
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
    _rejected(models.MatchedComparisonPlan, _identical_variants(payload)["plan"])
    for reference in ("SKILL.md", "references/evals.yaml"):
        _rejected(models.MatchedComparisonPlan, _invalid_reference(payload, reference)["plan"])
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
    """Bind fixture descriptors to a newly declared lane protocol, not old observations."""
    changed = json.loads(json.dumps(payload))
    plan = changed.get("plan") or changed["handoff"]["cloud_plan"]
    if "lanes" in plan:
        lane = "local" if "plan" in changed else "cloud"
        for specification in plan["lanes"]:
            if specification["lane"] == lane:
                specification["generator_mode"] = mode
    for execution in changed["executions"]:
        variants = execution.values() if "baseline" in execution else (execution,)
        for variant in variants:
            variant["provider"]["descriptor"]["mode"] = mode
    return changed


def _mixed_mode(payload: dict[str, object]) -> dict[str, object]:
    """Keep the declared mode unchanged while changing one supplied descriptor."""
    changed = json.loads(json.dumps(payload))
    descriptor = changed["executions"][0]["baseline"]["provider"]["descriptor"]
    descriptor["mode"] = "stream" if descriptor["mode"] == "complete" else "complete"
    return changed


def _encoding_boundary(payload: dict[str, object]) -> None:
    """Installed source-backed context rejects freshly captured unreadable text."""
    from skills_sdk.core.errors import ContractError
    from skills_sdk.validation import validate_plugin_package

    item = _variant(payload["executions"][0]["baseline"])
    context = item.plugin_context
    target = context.root / context.reference_paths[0]
    original = target.read_bytes()
    try:
        target.write_bytes(b"\xff\xfe")
        capture = validate_plugin_package(context.root, source_revision=context.validation.candidate.source_revision)
        assert capture.status == "pass"
        try:
            evaluation.prepare_matched_plugin_context(item.definition, replace(context, validation=capture))
        except ContractError as error:
            assert error.code == "invalid_matched_plugin_context" and "UTF-8" in error.message
        else:
            raise AssertionError("Fresh invalid UTF-8 reached provider context")
    finally:
        target.write_bytes(original)
    recovered = evaluation.prepare_matched_plugin_context(item.definition, context)
    assert recovered == item.inputs.payload


def _identical_variants(payload: dict[str, object]) -> dict[str, object]:
    """Build a consistently bound A/A input, not an unrelated field mismatch."""
    changed = json.loads(json.dumps(payload))
    plan = changed["plan"]
    scope = plan["plugin_scope"]
    scope["candidate"] = scope["baseline"]
    scope["candidate_coverage"] = scope["baseline_coverage"]
    plan["candidate_scenarios"] = plan["baseline_scenarios"]
    for case in scope["cases"]:
        case["candidate_scorer"] = case["baseline_scorer"]
    for binding in plan["case_bindings"]:
        binding["candidate_input_sha256"] = binding["baseline_input_sha256"]
        binding["candidate_scenario_set_id"] = binding["baseline_scenario_set_id"]
    for lane in plan["lanes"]:
        lane["candidate_calibration_sha256"] = lane["baseline_calibration_sha256"]
    changed["calibrations"][1] = changed["calibrations"][0]
    for pair in changed["executions"]:
        pair["candidate"] = pair["baseline"]
    return changed


def _invalid_reference(payload: dict[str, object], reference: str) -> dict[str, object]:
    """Retain captured source while supplying an ineligible generator reference."""
    changed = json.loads(json.dumps(payload))
    scope = changed["plan"]["plugin_scope"]
    case = scope["cases"][0]
    assert case["driver_skill_path"] in case["selected_skill_paths"]
    path = f"{case['driver_skill_path']}/{reference}"
    for capture in (scope["baseline"], scope["candidate"]):
        assert path in {item["path"] for item in capture["files"]}
    case["reference_paths"] = [path]
    for variant in changed["executions"][0].values():
        variant["plugin_context"]["reference_paths"] = [path]
    return changed


def _changed_baseline_calibration(recovery: dict[str, object]) -> dict[str, object]:
    """Keep calibration passing but change the frozen baseline experiment control."""
    changed = json.loads(json.dumps(recovery))
    bundle = changed["calibrations"][0]
    bundle["targets"][0]["receipt"]["calibration"]["plan"]["policy"]["max_false_positives"] = 1
    assert models.MatchedVariantCalibrationBundle.model_validate(bundle).targets[0].receipt.status == "pass"
    initial = changed["initial"].get("execution") or changed["initial"]
    for lane in changed["plan"]["lanes"]:
        if lane["lane"] == initial["lane"]:
            lane["baseline_calibration_sha256"] = canonical_json_sha256(bundle)
    models.MatchedComparisonPlan.model_validate(changed["plan"])
    return changed


def _cloud_blocker_text(root: Path) -> None:
    """Require the installed text route to expose the same blocker as JSON."""
    receipt = _cli(root, "matched-cloud-regression", {}, "matched-cloud-regression.v1", 2)
    executable = Path(sys.executable).with_name("skills-sdk.exe" if sys.platform == "win32" else "skills-sdk")
    result = subprocess.run(
        [
            str(executable),
            "eval",
            "matched-cloud-regression",
            "--input",
            str(root / "host-input.json"),
            "--adapter-mode",
            "supplied-offline",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    blocker = receipt["feedback"]["blocker"]
    assert result.returncode == 2 and not result.stderr, (result.returncode, result.stdout, result.stderr)
    assert f"{blocker['code']}: {blocker['message']}" in result.stdout


def _mixed_roots(root: Path, payload: dict[str, object]) -> dict[str, object]:
    """Retain exact source identities while moving one case to another copy."""
    changed = json.loads(json.dumps(payload))
    variant = changed["executions"][1]["candidate"]
    context = variant["plugin_context"]
    shutil.copytree(Path(context["root"]), root)
    variant["package_root"] = str(root / context["driver_skill_path"])
    context["root"] = str(root)
    return changed


def _feedback_api(recovery: dict[str, object], mixed: dict[str, object]) -> None:
    """Reject changed controls before host access, then close a corrected public API run."""

    class Trap:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"premature regression capability access: {name}")

    def frames(payload: dict[str, object], trap: bool) -> tuple[object, ...]:
        batch = tuple(
            evaluation.MatchedCaseExecution(_variant(item["baseline"]), _variant(item["candidate"]))
            for item in payload["executions"]
        )
        return tuple(
            replace(pair, candidate=replace(pair.candidate, provider=Trap(), judge=Trap())) if trap else pair
            for pair in batch
        )

    for payload, guarded, expected in (
        (mixed, True, "blocked"),
        (_changed_baseline_calibration(recovery), True, "blocked"),
        (recovery, False, "closed"),
    ):
        receipt = asyncio.run(
            evaluation.execute_matched_regression(
                payload["initial"],
                tuple(payload["assignments"]),
                payload["plan"],
                tuple(payload["calibrations"]),
                frames(payload, guarded),
            )
        )
        assert receipt.status == expected
        if expected == "blocked":
            assert receipt.blocker.code == "invalid_matched_feedback" and receipt.rerun is None
        SchemaRegistry().validate("matched-regression.v1", receipt.model_dump(mode="json"))


def _cli_workflow(root: Path, local: dict[str, object], numeric: object, cloud: object) -> None:
    """Prove all five installed routes for the selected fixture protocol."""
    for payload, code in (
        (local, 0),
        (dict(local, executions=local["executions"][:-1]), 2),
        (_provider_mode(local, "unsupported"), 2),
        (_mixed_mode(local), 2),
        (_identical_variants(local), 2),
        (_invalid_reference(local, "SKILL.md"), 2),
        (_invalid_reference(local, "references/evals.yaml"), 2),
        (local, 0),
    ):
        result = _cli(root, "matched-local", payload, "matched-execution.v1", code)
        assert result["provider_invocation_count"] == (40 if code == 0 else 0)
    for payload, code in ((numeric, 0), (dict(numeric, extra=True), 2), (numeric, 0)):
        result = _cli(root, "matched-calibration", payload, "matched-calibration.v1", code)
        assert result["status"] == ("pass" if code == 0 else "blocked")
        if code == 0:
            assert result["calibration"]["judge_invocation_count"] == 12
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
        changed_calibration = _cli(root, route, _changed_baseline_calibration(recovery), schema, 2)
        feedback = changed_calibration if command == "matched-local" else changed_calibration["feedback"]
        assert feedback["status"] == "blocked" and feedback["rerun"] is None
        mode = payload["executions"][0]["candidate"]["provider"]["descriptor"]["mode"]
        mixed = _mixed_roots(root / f"{route}-{mode}-copy", recovery)
        rejected = _cli(root, route, mixed, schema, 2)
        feedback = rejected if command == "matched-local" else rejected["feedback"]
        assert feedback["status"] == "blocked" and feedback["rerun"] is None
        if command == "matched-local" and mode == "complete":
            _feedback_api(recovery, mixed)
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
    _encoding_boundary(local)
    _cloud_blocker_text(root)
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
