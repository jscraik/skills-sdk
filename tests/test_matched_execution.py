"""Real ten-case paired callbacks, whole-batch rejection and recovery."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError
from test_live_selected_case import _Provider
from test_matched_calibration import DimensionJudge
from test_matched_comparison import _plan
from test_plugin_pre_execution_safety import _evidence as plugin_safety_fixture
from test_selected_case_evaluation import REVISION, _case, _prepared_request, _safety_for, _skill

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.evaluation.matched_admission import MatchedCaseExecution, MatchedTrialAdapters, MatchedVariantExecution
from skills_sdk.evaluation.matched_calibration import execute_matched_calibration
from skills_sdk.evaluation.matched_execution import execute_matched_lane
from skills_sdk.evaluation.matched_plugin_context import PluginExecutionContext, prepare_matched_plugin_context
from skills_sdk.evaluation.observed_calibration import CalibrationProbeExecution
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.evaluation.selected_case import load_selected_case
from skills_sdk.evaluation.skill_context import prepare_selected_case_context
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.models.matched_execution import MatchedExecutionReceipt
from skills_sdk.models.matched_plugin_calibration import MatchedCalibrationTarget, MatchedVariantCalibrationBundle
from skills_sdk.models.observed_calibration import ObservedCalibrationPlan
from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI
from skills_sdk.models.scorer_quality import ScorerJudgeParameters
from skills_sdk.validation import validate_plugin_package


class MatchedProvider(_Provider):
    def __init__(self, request: object, events: list[str]) -> None:
        super().__init__(request, events)
        self.parameters = ScorerJudgeParameters(model=request.provider.model_id, temperature=0.0, trial_count=1)

    async def complete(self, request: object, input_payload: object) -> object:
        assert request.input_sha256 == canonical_json_sha256(input_payload)
        assert request.candidate.model_dump(mode="json") in [
            item["candidate"] for item in input_payload["plugin_context"]["selected_skills"]
        ]
        return await super().complete(request, input_payload)


def _plugin_definitions(root: Path, score: float, count: int) -> tuple[object, ...]:
    """Create exactly ten managed driver cases across the captured plugin children."""
    (root / "skills").mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"$schema": PLUGIN_SCHEMA_URI, "name": "matched-fixture"}))
    (root / "shared.md").write_text("Shared bounded guidance.\n")
    cases = [_case(f"case-{index}", ["release"]) for index in range(10)]
    cases[-1]["category"] = "regression"
    packages = []
    for index in range(count):
        name = "simplify" if index == 0 else f"supplement-{index}"
        package = _skill(root / "skills" / name)
        source = (package / "SKILL.md").read_text().replace("name: simplify", f"name: {name}")
        (package / "SKILL.md").write_text(source + f"\nVariant instructions {score}.\n")
        subset = [case for number, case in enumerate(cases) if number % count == index]
        (package / "references/evals.yaml").write_text(
            yaml.safe_dump({"schema_version": "2.0", "skill_name": name, "cases": subset}), encoding="utf-8"
        )
        packages.append(package)
    return tuple(
        load_selected_case(packages[index % count], source_revision=REVISION, case_id=case["id"], mode="release")
        for index, case in enumerate(cases)
    )


def _calibrate_child(
    definition: object, request: object, rubric: object, parameters: object, events: list[str]
) -> object:
    """Observe held-out outputs for this exact child/assertion/scorer target."""
    payload = prepare_selected_case_context(definition)
    request = request.model_copy(update={"input_sha256": canonical_json_sha256(payload)})
    identity = request.candidate.model_dump(mode="json")
    scorer = _plan().plugin_scope.cases[0].baseline_scorer.model_dump(mode="json")
    scorer.update(candidate=identity, calibration_probe_ids=[f"held-out-{index}" for index in range(6)])
    texts = [f"calibration output {index}" for index in range(6)]
    calibration = ObservedCalibrationPlan.model_validate(
        {
            "candidate": identity,
            "scorer": scorer,
            "judge": request.provider.model_dump(mode="json"),
            "parameters": parameters.model_dump(mode="json"),
            "assertion_contract_sha256": definition.assertion_contract_sha256,
            "policy": {
                "threshold": 0.5,
                "minimum_examples": 6,
                "minimum_true_positives": 1,
                "minimum_true_negatives": 1,
                "max_false_positives": 0,
                "max_false_negatives": 0,
            },
            "probes": [
                {
                    "probe_id": f"held-out-{index}",
                    "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "expected_label": "pass" if index % 2 == 0 else "fail",
                }
                for index, text in enumerate(texts)
            ],
        }
    )
    frames = tuple(
        CalibrationProbeExecution(
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events, text),
            DimensionJudge(
                SimpleNamespace(
                    identity=request.provider, parameters=parameters, definition=definition, request=request
                ),
                4.5 if index % 2 == 0 else 0.5,
                events,
            ),
        )
        for index, text in enumerate(texts)
    )
    from skills_sdk.evaluation import CalibrationTrialAdapters

    frames = tuple(
        replace(
            frame,
            trial_adapters=tuple(
                CalibrationTrialAdapters(
                    _Provider(frame.request, events, frame.provider.text),
                    DimensionJudge(frame.judge, frame.judge.score, events),
                )
                for _ in range(parameters.trial_count - 1)
            ),
        )
        for frame in frames
    )
    receipt = asyncio.run(execute_matched_calibration(calibration, rubric, frames))
    assert receipt.status == "pass"
    return receipt


def _variant(
    root: Path, score: float, rubric: object, events: list[str], settings: tuple[int, object | None, int]
) -> tuple[object, object, tuple[object, ...]]:
    trials, provider_identity, count = settings
    definitions = _plugin_definitions(root, score, count)
    capture = validate_plugin_package(root, source_revision=REVISION)
    safety = plugin_safety_fixture(root, risky=True).model_copy(update={"observed_at": datetime.now(UTC)})
    paths = tuple(child.path for child in capture.skills)
    contexts = tuple(
        PluginExecutionContext(
            root.resolve(),
            capture,
            str(definition._package_root.relative_to(root.resolve())),
            paths if count > 1 and index == 9 else (str(definition._package_root.relative_to(root.resolve())),),
            ("shared.md",),
            safety_evidence=safety,
        )
        for index, definition in enumerate(definitions)
    )
    inputs = tuple(
        prepare_matched_plugin_context(definition, context)
        for definition, context in zip(definitions, contexts, strict=True)
    )
    requests = tuple(
        _prepared_request(definition, payload) for definition, payload in zip(definitions, inputs, strict=True)
    )
    if provider_identity is not None:
        requests = tuple(request.model_copy(update={"provider": provider_identity}) for request in requests)
    parameters = ScorerJudgeParameters(model=requests[0].provider.model_id, temperature=0.0, trial_count=trials)
    targets = {}
    for definition, request, context in zip(definitions, requests, contexts, strict=True):
        key = (context.driver_skill_path, definition.assertion_contract_sha256)
        if key not in targets:
            receipt = _calibrate_child(definition, request, rubric, parameters, events)
            targets[key] = MatchedCalibrationTarget(
                skill_path=key[0],
                child_candidate=request.candidate,
                assertion_contract_sha256=key[1],
                scorer=receipt.calibration.plan.scorer,
                receipt=receipt,
            )
    bundle = MatchedVariantCalibrationBundle(
        plugin_candidate=capture.candidate,
        mode_manifest_sha256=capture.mode_manifest_sha256,
        judge=requests[0].provider,
        judge_parameters=parameters,
        rubric=rubric,
        targets=tuple(targets[key] for key in sorted(targets)),
    )

    def adapters(definition: object, request: object) -> MatchedTrialAdapters:
        provider = MatchedProvider(request, events)
        provider.parameters = parameters
        judge = DimensionJudge(
            SimpleNamespace(identity=request.provider, parameters=parameters, definition=definition, request=request),
            score,
            events,
        )
        return MatchedTrialAdapters(provider, judge)

    executions = []
    for definition, request, payload, context in zip(definitions, requests, inputs, contexts, strict=True):
        first = adapters(definition, request)
        executions.append(
            MatchedVariantExecution(
                definition,
                request,
                SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
                first.provider,
                first.judge,
                context,
                tuple(adapters(definition, request) for _ in range(trials - 1)),
            )
        )
    scorers = tuple(
        targets[(context.driver_skill_path, definition.assertion_contract_sha256)].scorer
        for context, definition in zip(contexts, definitions, strict=True)
    )
    return scorers, bundle, tuple(executions)


def _matched(
    root: Path, trials: int = 2, variants: tuple[float, float, str] = (2.5, 4.5, "local"), child_count: int = 1
) -> tuple[object, tuple[object, object], tuple[object, ...], list[str]]:
    rubric = _plan().rubric
    events: list[str] = []
    settings = (trials, None if variants[2] == "local" else _plan().lanes[1].generator, child_count)
    left_scorers, left_receipt, left = _variant(root / "baseline", variants[0], rubric, events, settings)
    right_scorers, right_receipt, right = _variant(root / "candidate", variants[1], rubric, events, settings)
    raw = _plan().model_dump(mode="json")
    scope = raw["plugin_scope"]
    for name, frames in (("baseline", left), ("candidate", right)):
        capture = frames[0].plugin_context.validation
        raw[f"{name}_scenarios"] = [frame.definition.scenario_set.model_dump(mode="json") for frame in frames]
        scope[name] = capture.model_dump(mode="json")
        scope[f"{name}_coverage"]["candidate"] = capture.candidate.model_dump(mode="json")
    scope["cases"] = [
        {
            "case_id": a.request.case_id,
            "scope": "cross_skill" if len(a.plugin_context.selected_skill_paths) > 1 else "per_skill",
            "driver_skill_path": a.plugin_context.driver_skill_path,
            "selected_skill_paths": a.plugin_context.selected_skill_paths,
            "reference_paths": a.plugin_context.reference_paths,
            "baseline_scorer": ls.model_dump(mode="json"),
            "candidate_scorer": rs.model_dump(mode="json"),
            "claim_ids": [f"claim-{index}"],
        }
        for index, (a, ls, rs) in enumerate(zip(left, left_scorers, right_scorers, strict=True))
    ]
    raw["case_bindings"] = [
        {
            "case_id": a.request.case_id,
            "baseline_scenario_set_id": a.request.scenario_set_id,
            "candidate_scenario_set_id": b.request.scenario_set_id,
            "assertion_contract_sha256": a.definition.assertion_contract_sha256,
            "check_contract_sha256": a.definition.check_contract_sha256,
            "baseline_input_sha256": a.request.input_sha256,
            "candidate_input_sha256": b.request.input_sha256,
            "semantic_signal_ids": a.definition.semantic_signal_ids,
        }
        for a, b in zip(left, right, strict=True)
    ]
    lane = raw["lanes"][0 if variants[2] == "local" else 1]
    lane.update(
        generator=left[0].request.provider.model_dump(mode="json"),
        judge=left[0].judge.identity.model_dump(mode="json"),
        generator_parameters=left[0].provider.parameters.model_dump(mode="json"),
        judge_parameters=left[0].judge.parameters.model_dump(mode="json"),
        baseline_calibration_sha256=canonical_json_sha256(left_receipt.model_dump(mode="json")),
        candidate_calibration_sha256=canonical_json_sha256(right_receipt.model_dump(mode="json")),
    )
    events.clear()
    return (
        MatchedComparisonPlan.model_validate(raw),
        (left_receipt, right_receipt),
        tuple(MatchedCaseExecution(a, b) for a, b in zip(left, right, strict=True)),
        events,
    )


def test_actual_ten_case_pairs_and_context(tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "completed" and len(result.pairs) == 20
    assert result.provider_invocation_count == result.judge_invocation_count == 40
    assert events.count("provider") == events.count("dimensional_judge") == 40
    assert all(result.comparison(index).decision == "candidate" for index in range(20))


def test_incomplete_batch_zero_access_then_recovers(tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch[:-1]))
    assert (
        result.status == "blocked"
        and result.provider_invocation_count == result.judge_invocation_count == 0
        and not events
    )
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


def test_insufficient_lane_trials_reject_before_callbacks_and_recover(tmp_path: Path) -> None:
    """Reject a plan that cannot meet its selection policy before capability access."""
    plan, calibrations, batch, events = _matched(tmp_path)
    raw = plan.model_dump(mode="json")
    raw["lanes"][0]["generator_parameters"]["trial_count"] = 1
    raw["lanes"][0]["judge_parameters"]["trial_count"] = 1
    forged = MatchedComparisonPlan.model_construct(**raw)
    blocked = asyncio.run(execute_matched_lane(forged, "local", calibrations, batch))
    assert blocked.status == "blocked" and blocked.blocker.code == "invalid_matched_execution"
    assert blocked.provider_invocation_count == blocked.judge_invocation_count == 0 and not events
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


def test_late_request_mismatch_rejects_before_any_capability_access(tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)

    class CapabilityTrap:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"premature capability access: {name}")

    guarded = tuple(
        MatchedCaseExecution(
            replace(pair.baseline, provider=CapabilityTrap(), judge=CapabilityTrap()),
            replace(pair.candidate, provider=CapabilityTrap(), judge=CapabilityTrap()),
        )
        for pair in batch
    )
    last = guarded[-1]
    bad = replace(last.candidate, request=last.candidate.request.model_copy(update={"case_id": "unbound-case"}))
    guarded = (*guarded[:-1], replace(last, candidate=bad))
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, guarded))
    assert (
        result.status == "blocked"
        and not events
        and result.provider_invocation_count == result.judge_invocation_count == 0
    )
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


def test_settings_drift_after_callback_retains_first_stop_counts_and_recovers(tmp_path: Path) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    provider = batch[0].candidate.provider
    original = provider.complete

    async def drift(request: object, payload: object) -> object:
        value = await original(request, payload)
        provider.parameters = provider.parameters.model_copy(update={"temperature": 0.2})
        return value

    provider.complete = drift
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "blocked" and not result.pairs
    assert result.provider_invocation_count == 2 and result.judge_invocation_count == 1
    provider.parameters = plan.lanes[0].generator_parameters
    provider.complete = original
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


def test_retained_receipt_round_trip_and_forgery_rejection(tmp_path: Path) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert MatchedExecutionReceipt.model_validate_json(result.model_dump_json()) == result
    for updates in (
        {"provider_invocation_count": 0},
        {"promotion_authorized": True},
        {"pairs": result.pairs[:-1]},
        {"calibrations": tuple(reversed(result.calibrations))},
    ):
        with pytest.raises(ValidationError):
            MatchedExecutionReceipt.model_validate(result.model_copy(update=updates))


def test_maximum_local_trials_observe_each_pair_and_round_trip(tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path, trials=4)
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "completed" and len(result.pairs) == 40
    assert result.provider_invocation_count == result.judge_invocation_count == 80
    assert events.count("provider") == events.count("dimensional_judge") == 80
    assert [(pair.case_id, pair.trial_index) for pair in result.pairs] == [
        (f"case-{case}", trial) for case in range(10) for trial in range(4)
    ]
    assert MatchedExecutionReceipt.model_validate_json(result.model_dump_json()) == result


def test_late_judge_drift_retains_only_completed_prefix_and_recovers(tmp_path: Path) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    judge = batch[3].candidate.judge
    original = judge.judge

    async def drift(inputs: object) -> object:
        verdict = await original(inputs)
        judge.parameters = judge.parameters.model_copy(update={"temperature": 0.2})
        return verdict

    judge.judge = drift
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "blocked" and len(result.pairs) == 6
    assert result.provider_invocation_count == result.judge_invocation_count == 14
    assert MatchedExecutionReceipt.model_validate_json(result.model_dump_json()) == result
    judge.parameters = plan.lanes[0].judge_parameters
    judge.judge = original
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


def test_retained_evaluation_cannot_substitute_another_output(tmp_path: Path) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    raw = result.model_dump(mode="json")
    raw["pairs"][0]["candidate_evaluation"]["case_results"][0]["observation_sha256"] = "e" * 64
    with pytest.raises(ValidationError, match="selected-case evaluation"):
        MatchedExecutionReceipt.model_validate(raw)
    assert MatchedExecutionReceipt.model_validate(result).status == "completed"


def test_high_judge_score_cannot_hide_deterministic_candidate_failure(tmp_path: Path) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    provider = batch[0].candidate.provider
    provider.text = "behavior preserved; rm -rf"
    result = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert result.status == "completed" and result.comparison(0).decision == "candidate"
    assert result.pairs[0].candidate_evaluation.status == "fail"
    assert result.requires_regression
    provider.text = "behavior preserved"
    corrected = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert corrected.status == "completed" and not corrected.requires_regression


def test_full_check_digest_retains_deterministic_patterns(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")
    source = package / "references/evals.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    raw["cases"][0]["acceptance"].append({"type": "contains", "value": "original pattern"})
    source.write_text(yaml.safe_dump(raw), encoding="utf-8")
    original = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    raw["cases"][0]["acceptance"][-1]["value"] = "weakened pattern"
    source.write_text(yaml.safe_dump(raw), encoding="utf-8")
    changed = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    assert original.assertion_contract_sha256 == changed.assertion_contract_sha256
    assert original.scenario_set.cases == changed.scenario_set.cases
    assert original.check_contract_sha256 != changed.check_contract_sha256


def test_changed_full_check_commitment_blocks_all_callbacks_then_recovers(tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)
    raw = plan.model_dump(mode="json")
    raw["case_bindings"][-1]["check_contract_sha256"] = "e" * 64
    blocked = asyncio.run(execute_matched_lane(raw, "local", calibrations, batch))
    assert blocked.status == "blocked" and blocked.provider_invocation_count == 0 and not events
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"
