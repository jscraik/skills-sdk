"""Native dimensional callbacks, exact consumer joins and frozen numeric neighbours."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_live_selected_case import _Provider
from test_matched_calibration import DimensionJudge, _dimensions
from test_matched_comparison import _judgment, _plan
from test_matched_execution import _matched
from test_selected_case_evaluation import _prepared_request, _safety_for

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import assess_native_matched_pair, execute_native_matched_calibration
from skills_sdk.evaluation.matched_calibration import execute_matched_calibration
from skills_sdk.evaluation.observed_calibration import CalibrationProbeExecution
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.models import (
    CodexNativeJudgeParameters,
    NativeMatchedCalibrationReceipt,
    NativeMatchedCalibrationTarget,
    NativeMatchedComparisonPlan,
    NativeMatchedLaneSpec,
    NativeMatchedPairAssessment,
    NativeMatchedVariantCalibrationBundle,
)
from skills_sdk.models.matched_calibration import MatchedCalibrationReceipt, _dimension_digest
from skills_sdk.models.matched_comparison import MatchedComparisonPlan, MatchedVariantJudgment
from skills_sdk.models.matched_ingress import _canonical_matched_input
from skills_sdk.models.observed_calibration import NativeCalibrationPlan
from skills_sdk.models.provider import ProviderIdentityV2


def _native_identity(rubric: object) -> tuple[object, object]:
    parameters = CodexNativeJudgeParameters(
        model="native-fixture",
        cli_version="fixture-v1",
        reasoning_effort="medium",
        timeout_seconds=30,
        disabled_mcp_servers=(),
    )
    identity = ProviderIdentityV2(
        provider_id="codex",
        provider_kind="agent",
        model_id=parameters.model,
        version_or_digest=parameters.cli_version,
        adapter_id="codex-cli-judge",
        adapter_version_or_digest=canonical_json_sha256(
            {
                "settings": parameters.model_dump(mode="json", exclude={"schema_version"}),
                "rubric_sha256": canonical_json_sha256(rubric.model_dump(mode="json")),
            }
        ),
    )
    return parameters, identity


class NativeDimensionJudge(DimensionJudge):
    """Inert host callback supplies dimensions, not a scalar conversion."""

    async def judge(self, inputs: object) -> object:
        result = await super().judge(inputs)
        return MatchedVariantJudgment.model_validate(
            result.model_copy(
                update={
                    "evidence": result.evidence.model_copy(update={"judge": self.identity}),
                }
            )
        )


def _native_plan(original: object, rubric: object) -> NativeCalibrationPlan:
    parameters, identity = _native_identity(rubric)
    raw = original.model_dump(mode="json", exclude={"schema_version"})
    raw.update(
        parameters=parameters, judge=identity, rubric_sha256=canonical_json_sha256(rubric.model_dump(mode="json"))
    )
    return NativeCalibrationPlan.model_validate(raw)


def _native_dimensions(root: Path) -> tuple[object, object, list[str]]:
    original, frames, events = _dimensions(root)
    plan = _native_plan(original, _plan().rubric)
    converted = []
    for frame in frames:
        judge = NativeDimensionJudge(frame.judge, frame.judge.score, events)
        judge.parameters, judge.identity = plan.parameters, plan.judge
        converted.append(replace(frame, judge=judge))
    return plan, tuple(converted), events


def _observe_target(original: object, execution: object, rubric: object) -> object:
    plan = _native_plan(original.calibration.plan, rubric)
    definition = execution.definition
    payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, payload)
    events: list[str] = []
    frames = tuple(
        CalibrationProbeExecution(
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events, f"calibration output {index}"),
            NativeDimensionJudge(
                SimpleNamespace(
                    identity=plan.judge,
                    parameters=plan.parameters,
                    definition=definition,
                    request=request,
                ),
                4.5 if index % 2 == 0 else 0.5,
                events,
            ),
        )
        for index in range(6)
    )
    result = asyncio.run(execute_native_matched_calibration(plan, rubric, frames))
    assert result.status == "pass", result
    assert events.count("dimensional_judge") == 6
    return result


def _native_pair(root: Path) -> tuple[object, tuple[object, object]]:
    numeric, calibrations, pairs, _ = _matched(root, child_count=2)
    bundles = []
    for variant, bundle in zip(("baseline", "candidate"), calibrations, strict=True):
        targets = []
        for target in bundle.targets:
            execution = next(
                getattr(pair, variant)
                for pair in pairs
                if getattr(pair, variant).definition.scenario_set.candidate == target.child_candidate
                and getattr(pair, variant).definition.assertion_contract_sha256 == target.assertion_contract_sha256
            )
            receipt = _observe_target(target.receipt, execution, numeric.rubric)
            targets.append(
                NativeMatchedCalibrationTarget(
                    skill_path=target.skill_path,
                    child_candidate=target.child_candidate,
                    assertion_contract_sha256=target.assertion_contract_sha256,
                    scorer=target.scorer,
                    receipt=receipt,
                )
            )
        parameters, identity = _native_identity(numeric.rubric)
        bundles.append(
            NativeMatchedVariantCalibrationBundle(
                plugin_candidate=bundle.plugin_candidate,
                mode_manifest_sha256=bundle.mode_manifest_sha256,
                judge=identity,
                judge_parameters=parameters,
                rubric=numeric.rubric,
                targets=tuple(targets),
            )
        )
    raw = numeric.model_dump(mode="json", exclude={"schema_version"})
    for lane in raw["lanes"]:
        lane.update(
            judge=identity,
            judge_parameters=parameters,
            baseline_calibration_sha256=canonical_json_sha256(bundles[0].model_dump(mode="json")),
            candidate_calibration_sha256=canonical_json_sha256(bundles[1].model_dump(mode="json")),
        )
    return NativeMatchedComparisonPlan.model_validate(raw), tuple(bundles)


def _pair_judgment(plan: object, variant: str, score: float) -> MatchedVariantJudgment:
    result = _judgment(plan, variant, score)
    result = MatchedVariantJudgment.model_validate(
        result.model_copy(
            update={
                "evidence": result.evidence.model_copy(
                    update={
                        "assertion_contract_sha256": plan.case_bindings[0].assertion_contract_sha256,
                    }
                ),
            }
        )
    )
    digest = _dimension_digest(plan.rubric, result)
    return MatchedVariantJudgment.model_validate(
        result.model_copy(
            update={
                "evidence": result.evidence.model_copy(
                    update={
                        "judge_result_sha256": digest,
                        "evidence_refs": (*result.evidence.evidence_refs, f"judge-results/{digest}"),
                    }
                ),
            }
        )
    )


def test_native_dimensional_producer_rejects_numeric_consumer_and_recovers(tmp_path: Path) -> None:
    plan, frames, events = _native_dimensions(tmp_path)
    assert asyncio.run(execute_matched_calibration(plan, _plan().rubric, frames)).status == "blocked"
    assert not events
    result = asyncio.run(execute_native_matched_calibration(plan, _plan().rubric, frames))
    assert result.status == "pass" and result.calibration.judge_invocation_count == 6
    assert [row.score for row in result.calibration.results] == [0.9, 0.1] * 3
    assert NativeMatchedCalibrationReceipt.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError):
        MatchedCalibrationReceipt.model_validate(result)


def test_native_supplied_consumer_requires_both_exact_bundles(tmp_path: Path) -> None:
    plan, bundles = _native_pair(tmp_path)
    left, right = _pair_judgment(plan, "baseline", 2.5), _pair_judgment(plan, "candidate", 4.0)
    result = assess_native_matched_pair(plan, "local", bundles, left, right)
    assert result.status == "assessed" and result.decision == "candidate", result
    assert not result.execution_performed and not result.promotion_authorized
    assert NativeMatchedPairAssessment.model_validate_json(result.model_dump_json()) == result
    assert assess_native_matched_pair(plan, "local", bundles[:1], left, right).status == "blocked"
    assert assess_native_matched_pair(plan, "local", bundles[::-1], left, right).status == "blocked"
    assert assess_native_matched_pair(plan, "local", bundles, left, right).status == "assessed"
    with pytest.raises(ValidationError):
        MatchedComparisonPlan.model_validate(plan)


@pytest.fixture(scope="module")
def native_pair_fixture(tmp_path_factory: pytest.TempPathFactory) -> tuple[object, object]:
    return _native_pair(tmp_path_factory.mktemp("native-pair"))


@pytest.mark.parametrize("change", ["score", "reason", "candidate", "assertions", "output", "missing", "confidence"])
def test_native_dimensional_tamper_rejects_and_recovers(tmp_path: Path, change: str) -> None:
    plan, frames, _events = _native_dimensions(tmp_path)
    result = asyncio.run(execute_native_matched_calibration(plan, _plan().rubric, frames))
    raw = result.model_dump(mode="json")
    judgment = raw["judgments"][0]
    if change == "score":
        judgment["dimensions"][0]["score"] = 1.0
    elif change == "reason":
        judgment["dimensions"][0]["rationale"] = "Changed evidence."
    elif change == "candidate":
        judgment["evidence"]["candidate"]["content_sha256"] = "0" * 64
    elif change in {"assertions", "output"}:
        judgment["evidence"]["assertion_contract_sha256" if change == "assertions" else "output_sha256"] = "0" * 64
    elif change == "missing":
        judgment["dimensions"].pop()
    else:
        judgment["confidence"] = "low"
    with pytest.raises(ValidationError):
        NativeMatchedCalibrationReceipt.model_validate(raw)
    with pytest.raises(ValidationError):
        NativeMatchedCalibrationReceipt.model_validate_json(json.dumps(raw))
    assert NativeMatchedCalibrationReceipt.model_validate(result) == result


@pytest.mark.parametrize("change", ["settings", "identity", "judge_callback", "cleanup_callback", "alias"])
def test_later_invalid_capability_blocks_all_dispatch(tmp_path: Path, change: str) -> None:
    plan, frames, events = _native_dimensions(tmp_path)
    last = frames[-1].judge
    if change == "settings":
        last.parameters = last.parameters.model_copy(update={"timeout_seconds": 31})
    elif change == "identity":
        last.identity = last.identity.model_copy(update={"adapter_version_or_digest": "drift"})
    elif change == "judge_callback":
        last.judge = None
    elif change == "cleanup_callback":
        last.cleanup = None
    else:
        frames = (*frames[:-1], replace(frames[-1], judge=frames[0].judge))
    result = asyncio.run(execute_native_matched_calibration(plan, _plan().rubric, frames))
    assert result.status == "blocked" and result.calibration is None and not events


def test_late_source_mismatch_precedes_capability_access(tmp_path: Path) -> None:
    plan, frames, events = _native_dimensions(tmp_path)

    class Trap:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"premature capability access: {name}")

    guarded = tuple(replace(frame, provider=Trap(), judge=Trap()) for frame in frames)
    last = guarded[-1]
    guarded = (*guarded[:-1], replace(last, request=last.request.model_copy(update={"case_id": "wrong"})))
    result = asyncio.run(execute_native_matched_calibration(plan, _plan().rubric, guarded))
    assert result.status == "blocked" and not events
    assert asyncio.run(execute_native_matched_calibration(plan, _plan().rubric, frames)).status == "pass"


@pytest.mark.parametrize("member", ["complete", "cleanup", "descriptor"])
def test_later_invalid_provider_blocks_all_dispatch(tmp_path: Path, member: str) -> None:
    plan, frames, events = _native_dimensions(tmp_path)
    provider = frames[-1].provider
    original = getattr(provider, member)
    setattr(provider, member, None)
    rejected = asyncio.run(execute_native_matched_calibration(plan, _plan().rubric, frames))
    assert rejected.status == "blocked" and not events and rejected.calibration is None
    setattr(provider, member, original)
    assert asyncio.run(execute_native_matched_calibration(plan, _plan().rubric, frames)).status == "pass"


@pytest.mark.parametrize("failure", ["cleanup", "private_error", "cancelled", "scalar", "missing_dimensions"])
def test_failure_retains_honest_partial_counts_then_recovers(tmp_path: Path, failure: str) -> None:
    plan, frames, events = _native_dimensions(tmp_path)
    judge = frames[1].judge
    original_judge, original_cleanup = judge.judge, judge.cleanup

    async def broken_judge(inputs: object) -> object:
        if failure == "private_error":
            raise RuntimeError("private-marker-must-not-escape")
        if failure == "cancelled":
            raise asyncio.CancelledError
        result = await original_judge(inputs)
        if failure == "scalar":
            return {"evidence": result.evidence, "score": 0.1}
        return result.model_copy(update={"dimensions": result.dimensions[:1]})

    async def broken_cleanup() -> object:
        await original_cleanup()
        return False

    if failure == "cleanup":
        judge.cleanup = broken_cleanup
    else:
        judge.judge = broken_judge
    result = asyncio.run(execute_native_matched_calibration(plan, _plan().rubric, frames))
    assert result.status == "blocked" and result.calibration.judge_invocation_count == 2
    assert len(result.judgments) == len(result.calibration.results) == 1
    assert events.count("provider") == 2
    assert "private-marker" not in result.model_dump_json()


@pytest.mark.parametrize("change", ["candidate", "modes", "targets", "settings", "child", "extra"])
def test_reconstructed_bundle_binding_rejects_and_recovers(native_pair_fixture: object, change: str) -> None:
    """Reconstruct missing bundle-neighbour coverage; original bytes unavailable."""
    plan, bundles = native_pair_fixture
    raw = bundles[1].model_dump(mode="json")
    if change == "candidate":
        raw["plugin_candidate"]["source_revision"] = "f" * 40
    elif change == "modes":
        raw["mode_manifest_sha256"] = "f" * 64
    elif change == "targets":
        raw["targets"] = []
    elif change == "settings":
        raw["judge_parameters"]["timeout_seconds"] = 31
    elif change == "child":
        raw["targets"][0]["child_candidate"]["content_sha256"] = "f" * 64
    else:
        raw["unknown"] = "must not disappear"
    left, right = _pair_judgment(plan, "baseline", 2.5), _pair_judgment(plan, "candidate", 4.0)
    assert assess_native_matched_pair(plan, "local", (bundles[0], raw), left, right).status == "blocked"
    assert assess_native_matched_pair(plan, "local", bundles, left, right).status == "assessed"


@pytest.mark.parametrize("change", ["modes", "candidate"])
def test_reconstructed_rebound_bundle_still_requires_exact_capture(native_pair_fixture: object, change: str) -> None:
    """Reach the capture join after rebinding the superficial bundle digest."""
    plan, bundles = native_pair_fixture
    raw = bundles[1].model_dump(mode="json")
    if change == "modes":
        raw["mode_manifest_sha256"] = "f" * 64
    else:
        raw["plugin_candidate"]["source_revision"] = "f" * 40
    altered = NativeMatchedVariantCalibrationBundle.model_validate(raw)
    rebound = plan.model_dump(mode="json")
    for lane in rebound["lanes"]:
        lane["candidate_calibration_sha256"] = canonical_json_sha256(altered.model_dump(mode="json"))
    parsed = NativeMatchedComparisonPlan.model_validate(rebound)
    left, right = _pair_judgment(parsed, "baseline", 2.5), _pair_judgment(parsed, "candidate", 4.0)
    assert assess_native_matched_pair(parsed, "local", (bundles[0], altered), left, right).status == "blocked"
    original_left, original_right = _pair_judgment(plan, "baseline", 2.5), _pair_judgment(plan, "candidate", 4.0)
    assert assess_native_matched_pair(plan, "local", bundles, original_left, original_right).status == "assessed"


@pytest.mark.parametrize("change", ["trials", "case_count", "rubric", "settings", "digest", "dimensions"])
def test_native_plan_and_supplied_evidence_boundaries(native_pair_fixture: object, change: str) -> None:
    plan, bundles = native_pair_fixture
    raw = plan.model_dump(mode="json")
    left, right = _pair_judgment(plan, "baseline", 2.5), _pair_judgment(plan, "candidate", 4.0)
    if change == "trials":
        raw["lanes"][0]["generator_parameters"]["trial_count"] = 1
    elif change == "case_count":
        raw["case_bindings"].pop()
    elif change == "rubric":
        raw["rubric"]["dimensions"][0]["criterion"] = "Changed rubric."
    elif change == "settings":
        raw["lanes"][0]["judge_parameters"]["timeout_seconds"] = 31
    elif change == "digest":
        raw["lanes"][0]["baseline_calibration_sha256"] = "0" * 64
    else:
        right = right.model_copy(
            update={"dimensions": (right.dimensions[0].model_copy(update={"score": 3.9}), *right.dimensions[1:])}
        )
    assert assess_native_matched_pair(raw, "local", bundles, left, right).status == "blocked"


def test_native_ingress_rejects_forgery_cycles_and_coercion(native_pair_fixture: object) -> None:
    plan, bundles = native_pair_fixture
    source = bundles[0].targets[0].receipt
    cycle: list[object] = []
    cycle.append(cycle)
    for malformed in (cycle, list(range(65537))):
        with pytest.raises(ValidationError):
            NativeMatchedCalibrationReceipt.model_validate(source.model_copy(update={"judgments": malformed}))
    forged = source.judgments[0].model_copy(update={"unknown": "must not disappear"})
    with pytest.raises(ValidationError):
        NativeMatchedCalibrationReceipt.model_validate(
            source.model_copy(update={"judgments": (forged, *source.judgments[1:])})
        )
    for value in (0, "false", True):
        with pytest.raises(ValidationError):
            NativeMatchedCalibrationReceipt.model_validate(source.model_copy(update={"promotion_authorized": value}))
    with pytest.raises(ValidationError):
        NativeMatchedCalibrationReceipt.model_validate(source.calibration)
    assert NativeMatchedComparisonPlan.model_validate(plan) == plan


def test_native_public_packaged_schemas_and_semantics(native_pair_fixture: object) -> None:
    plan, bundles = native_pair_fixture
    left, right = _pair_judgment(plan, "baseline", 2.5), _pair_judgment(plan, "candidate", 4.0)
    result = assess_native_matched_pair(plan, "local", bundles, left, right)
    for artifact in (plan, bundles[0], bundles[0].targets[0].receipt, result):
        name = artifact.schema_version.replace("/", ".")
        SchemaRegistry().validate(name, artifact.model_dump(mode="json"))
        assert type(artifact).model_validate_json(artifact.model_dump_json()) == artifact


def test_external_caller_cancellation_cleans_started_capabilities(tmp_path: Path) -> None:
    plan, frames, events = _native_dimensions(tmp_path)

    async def scenario() -> None:
        started = asyncio.Event()

        async def wait_for_cancellation(inputs: object) -> object:
            started.set()
            await asyncio.Future()

        frames[0].judge.judge = wait_for_cancellation
        task = asyncio.create_task(execute_native_matched_calibration(plan, _plan().rubric, frames))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert events.count("provider") == events.count("provider_cleanup") == 1
    assert events.count("dimensional_cleanup") == 1


def test_native_ingress_graph_does_not_expand_numeric_ingress() -> None:
    parameters, _identity = _native_identity(_plan().rubric)
    with pytest.raises(ValueError, match="canonical"):
        _canonical_matched_input(parameters)
    assert _canonical_matched_input(parameters, native=True) == parameters.model_dump(mode="json")
    raw = {"apps": "ordinary caller data", "plugins": 3, "ephemeral": "text"}
    assert _canonical_matched_input(raw) == raw
    with pytest.raises(ValueError, match="Boolean"):
        _canonical_matched_input(raw, native=True)


def _with_native_mcp_names(plan: object, names: tuple[str, ...], form: str, index: int) -> tuple[object, object]:
    original = plan.lanes[index]
    parameters = original.judge_parameters.model_copy(update={"disabled_mcp_servers": names})
    identity = original.judge.model_copy(
        update={
            "adapter_version_or_digest": canonical_json_sha256(
                {
                    "settings": parameters.model_dump(mode="json", exclude={"schema_version"}),
                    "rubric_sha256": canonical_json_sha256(plan.rubric.model_dump(mode="json")),
                }
            )
        }
    )
    if form == "copied":
        lane = original.model_copy(update={"judge_parameters": parameters, "judge": identity})
        lanes = list(plan.lanes)
        lanes[index] = lane
        return plan.model_copy(update={"lanes": tuple(lanes)}), lane
    raw = plan.model_dump(mode="json")
    lane = raw["lanes"][index]
    lane.update(
        judge_parameters=parameters.model_dump(mode="json"),
        judge=identity.model_dump(mode="json"),
    )
    if form == "typed":
        lane.update(
            judge_parameters=CodexNativeJudgeParameters.model_validate(lane["judge_parameters"]),
            judge=ProviderIdentityV2.model_validate(lane["judge"]),
        )
    return raw, lane


@pytest.mark.parametrize("form", ["raw", "typed", "copied"])
@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("name", ["sk-fixture-not-a-secret", "ghp_fixture_not_a_secret", "AKIA_fixture_not_a_secret"])
def test_private_mcp_names_cannot_reach_native_plan_or_blocked_receipt(
    native_pair_fixture: object, form: str, index: int, name: str
) -> None:
    plan, bundles = native_pair_fixture
    malformed, lane = _with_native_mcp_names(plan, (name,), form, index)
    rejected = assess_native_matched_pair(malformed, "local", bundles, {}, {})
    assert rejected.status == "blocked" and rejected.plan is None
    assert name not in rejected.model_dump_json()
    assert NativeMatchedPairAssessment.model_validate_json(rejected.model_dump_json()) == rejected
    with pytest.raises(ValidationError, match="MCP names must be public identities"):
        NativeMatchedLaneSpec.model_validate(lane)
    with pytest.raises(ValidationError, match="MCP names must be public identities"):
        NativeMatchedComparisonPlan.model_validate(malformed)
    with pytest.raises(ValidationError, match="MCP names must be public identities"):
        NativeMatchedPairAssessment.model_validate(rejected.model_copy(update={"plan": malformed}))
    if form == "raw":
        with pytest.raises(ValidationError, match="MCP names must be public identities"):
            NativeMatchedComparisonPlan.model_validate_json(json.dumps(malformed))
        with pytest.raises(ContractError):
            SchemaRegistry().validate("native-matched-comparison-plan.v1", malformed)
        receipt = rejected.model_dump(mode="json")
        receipt["plan"] = malformed
        with pytest.raises(ContractError):
            SchemaRegistry().validate("native-matched-pair-assessment.v1", receipt)
    assert NativeMatchedComparisonPlan.model_validate(plan) == plan


@pytest.mark.parametrize("form", ["raw", "typed", "copied"])
def test_public_mcp_names_remain_valid_in_native_plan_and_blocked_receipt(
    native_pair_fixture: object, form: str
) -> None:
    plan, bundles = native_pair_fixture
    supplied, lane = _with_native_mcp_names(plan, ("filesystem", "github", "project_tools"), form, 1)
    parsed = NativeMatchedComparisonPlan.model_validate(supplied)
    assert NativeMatchedLaneSpec.model_validate(lane) == parsed.lanes[1]
    assert NativeMatchedComparisonPlan.model_validate_json(parsed.model_dump_json()) == parsed
    rejected = assess_native_matched_pair(supplied, "local", bundles, {}, {})
    assert rejected.status == "blocked" and rejected.plan == parsed
    assert NativeMatchedPairAssessment.model_validate_json(rejected.model_dump_json()) == rejected
