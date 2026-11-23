"""Offline native evidence joins through the maintained local workflow."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from test_local_check_cli import REVISION
from test_quality_workflow import _assessment, _request

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.evaluation.quality_workflow import check_local_quality
from skills_sdk.models.native_quality import NativeLocalCheckRequest, NativeLocalCheckResult
from skills_sdk.models.observed_calibration import (
    CalibrationJudgeVerdict,
    NativeCalibrationPlan,
    NativeCalibrationReceipt,
)
from skills_sdk.providers.codex_judge import CodexJudgeSettings
from skills_sdk.validation import validate_skill_package


def _calibration_plan(scorer: dict, assertions: str, labels: tuple[str, ...]) -> NativeCalibrationPlan:
    """Construct synthetic supplied data, never live pilot evidence."""
    settings = CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ())
    return NativeCalibrationPlan.model_validate(
        {
            "candidate": scorer["candidate"],
            "scorer": scorer,
            "judge": {
                "provider_id": "codex",
                "provider_kind": "agent",
                "model_id": settings.model,
                "version_or_digest": settings.cli_version,
                "adapter_id": "codex-cli-judge",
                "adapter_version_or_digest": canonical_json_sha256(
                    {
                        "settings": settings.calibration_parameters().model_dump(
                            mode="json", exclude={"schema_version"}
                        ),
                        "rubric_sha256": "b" * 64,
                    }
                ),
            },
            "parameters": settings.calibration_parameters().model_dump(mode="json"),
            "assertion_contract_sha256": assertions,
            "rubric_sha256": "b" * 64,
            "policy": {
                "threshold": scorer["pass_threshold"],
                "minimum_examples": 6,
                "minimum_true_positives": 1,
                "minimum_true_negatives": 1,
                "max_false_positives": 0,
                "max_false_negatives": 0,
            },
            "probes": [
                {"probe_id": name, "output_sha256": f"{i + 1:064x}", "expected_label": labels[i]}
                for i, name in enumerate(scorer["calibration_probe_ids"])
            ],
        }
    )


def _observation(plan: NativeCalibrationPlan) -> NativeCalibrationReceipt:
    results = []
    for probe in plan.probes:
        score = 1.0 if probe.expected_label == "pass" else 0.0
        evidence = {
            "candidate": plan.candidate,
            "scenario_set_id": "held-out",
            "case_id": probe.probe_id,
            "provider": plan.judge,
            "judge": plan.judge,
            "output_sha256": probe.output_sha256,
            "assertion_contract_sha256": plan.assertion_contract_sha256,
            "judge_result_sha256": "c" * 64,
            "evidence_refs": ["evidence/controlled.json", "judge-results/" + "c" * 64],
        }
        verdict = CalibrationJudgeVerdict.model_validate({"evidence": evidence, "score": score})
        results.append(
            {
                "probe_id": probe.probe_id,
                "trial_index": 0,
                "output_sha256": probe.output_sha256,
                "expected_label": probe.expected_label,
                "predicted_label": probe.expected_label,
                "score": score,
                "judge_result_sha256": canonical_json_sha256(verdict.model_dump(mode="json")),
            }
        )
    return NativeCalibrationReceipt(
        plan=plan, status="pass", results=results, judge_invocation_count=len(results), judge_execution_performed=True
    )


def _fixture(root: Path, external: bool = False) -> tuple:
    request = _request(root)
    # Locate the package made by the maintained workflow fixture.
    package = next(root.rglob("SKILL.md")).parent
    path = package / "references/evals.yaml"
    data = yaml.safe_load(path.read_text())
    meta = data["scorer_quality"]
    if external:
        meta["scorer_type"] = "external_tessl"
        meta["rationale_audit"] = {"required": True, "sampled_count": 3}
    meta.update(
        schema_version="skills-sdk.native-scorer-quality.v1",
        parameters=CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()).calibration_parameters().model_dump(mode="json"),
    )
    path.write_text(yaml.safe_dump(data))
    candidate = validate_skill_package(package, source_revision=REVISION).candidate.model_dump(mode="json")
    scorer = {
        "candidate": candidate,
        "scorer_id": meta["scorer_id"],
        "scorer_type": "external" if external else meta["scorer_type"],
        "version_or_digest": meta["scorer_version_or_digest"],
        "pass_threshold": meta["pass_threshold"],
        "deterministic_checks_first": True,
        "calibration_required": True,
        "calibration_probe_ids": [case["id"] for case in meta["calibration_cases"]],
    }
    plan = _calibration_plan(
        scorer,
        "e" * 64,
        tuple("pass" if case["probe_type"] == "obvious_correct" else "fail" for case in meta["calibration_cases"]),
    )
    request.update(
        schema_version="native-local-check-request/v1",
        candidate=candidate,
        calibration_plan=plan.model_dump(mode="json"),
    )
    request["coverage_plan"]["candidate"] = candidate
    return package, request, _observation(plan)


def test_native_bridge_stops_recovers_and_round_trips(tmp_path: Path) -> None:
    package, request, observation = _fixture(tmp_path)
    blocked = asyncio.run(check_local_quality(package, request))
    assert blocked.blocked_stage == "scorer-calibration"
    passed = asyncio.run(
        check_local_quality(package, {**request, "calibration": observation}, assessment=_assessment(package))
    )
    assert passed.status == "local_checks_passed", passed
    assert passed.final_capture.candidate == passed.request.candidate
    assert not passed.evaluation_executed and not passed.promotion_authorized
    assert NativeLocalCheckResult.model_validate_json(passed.model_dump_json()) == passed
    with pytest.raises(ValidationError):
        NativeLocalCheckResult.model_validate(passed.model_copy(update={"stages": passed.stages[:-1]}))


@pytest.mark.parametrize("defect", ["ids", "order", "type", "settings", "plan", "labels"])
def test_native_bridge_rejects_substituted_evidence(tmp_path: Path, defect: str) -> None:
    package, request, observation = _fixture(tmp_path)
    raw = request["calibration_plan"]
    if defect == "ids":
        for i, probe in enumerate(raw["probes"]):
            probe["probe_id"] = f"replacement-{i}"
        raw["scorer"]["calibration_probe_ids"] = [p["probe_id"] for p in raw["probes"]]
    elif defect == "order":
        raw["probes"].reverse()
        raw["scorer"]["calibration_probe_ids"].reverse()
    elif defect == "type":
        raw["scorer"]["scorer_type"] = "hybrid"
    elif defect == "labels":
        for probe in raw["probes"]:
            probe["expected_label"] = "fail" if probe["expected_label"] == "pass" else "pass"
    elif defect == "plan":
        raw["assertion_contract_sha256"] = "a" * 64
    else:
        raw["parameters"]["reasoning_effort"] = "high"
    if defect in {"ids", "order", "type", "labels"}:
        observation = _observation(NativeCalibrationPlan.model_validate(raw))
    result = asyncio.run(check_local_quality(package, {**request, "calibration": observation}))
    assert result.status == "blocked"
    assert result.blocked_stage in {"request", "scorer-calibration"}


def test_legacy_request_rejects_supplied_native_calibration(tmp_path: Path) -> None:
    request = _request(tmp_path)
    package = next(tmp_path.rglob("SKILL.md")).parent
    result = asyncio.run(check_local_quality(package, {**request, "calibration": {}}))
    assert result.blocked_stage == "request"


@pytest.mark.parametrize("defect", ["partial", "failed", "copied", "subclass", "candidate"])
def test_invalid_observation_stops_before_content_review(tmp_path: Path, defect: str) -> None:
    package, request, observed = _fixture(tmp_path)
    if defect == "partial":
        observed = observed.model_copy(update={"results": observed.results[:-1]})
    elif defect == "failed":
        observed = observed.model_copy(update={"status": "blocked"})
    elif defect == "copied":
        observed = observed.model_copy(update={"judge_invocation_count": True})
    elif defect == "subclass":

        class UntrustedReceipt(NativeCalibrationReceipt):
            pass

        observed = UntrustedReceipt.model_validate(observed.model_dump())
    else:
        observed = observed.model_copy(
            update={
                "plan": observed.plan.model_copy(
                    update={"candidate": observed.plan.candidate.model_copy(update={"source_revision": "2" * 40})}
                )
            }
        )
    result = asyncio.run(check_local_quality(package, {**request, "calibration": observed}))
    assert result.blocked_stage == "request"
    assert not result.stages
    assert result.final_capture is None


def test_native_summary_and_result_reject_forged_bindings(tmp_path: Path) -> None:
    package, request, observed = _fixture(tmp_path)
    passed = asyncio.run(
        check_local_quality(package, {**request, "calibration": observed}, assessment=_assessment(package))
    )
    summary = passed.stages[-2].receipt
    from skills_sdk.models.native_quality import NativeScorerCalibrationReceipt

    for field, value in (("example_count", 7), ("prompt_version", "a" * 64), ("execution_performed", 0)):
        with pytest.raises(ValidationError):
            NativeScorerCalibrationReceipt.model_validate(summary.model_copy(update={field: value}))
    raw = passed.model_dump(mode="json")
    raw["request"]["calibration_plan"]["assertion_contract_sha256"] = "a" * 64
    with pytest.raises(ValidationError):
        NativeLocalCheckResult.model_validate(raw)


def test_native_schemas_and_semantic_registry(tmp_path: Path) -> None:
    from jsonschema import Draft202012Validator

    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry

    package, request, observed = _fixture(tmp_path)
    passed = asyncio.run(
        check_local_quality(package, {**request, "calibration": observed}, assessment=_assessment(package))
    )
    registry = SchemaRegistry()
    values = [
        ("native-local-check-request.v1", passed.request),
        ("native-local-check.v1", passed),
        ("native-scorer-quality.v1", passed.stages[-3].receipt),
        ("native-scorer-calibration.v1", passed.stages[-2].receipt),
    ]
    for name, value in values:
        payload = value.model_dump(mode="json")
        Draft202012Validator(registry.load(name)).validate(payload)
        registry.validate(name, payload)
    raw = passed.model_dump(mode="json")
    raw["stages"][-2]["receipt"]["prompt_version"] = "a" * 64
    with pytest.raises(ContractError):
        registry.validate("native-local-check.v1", raw)
    with pytest.raises(ValidationError):
        NativeLocalCheckRequest.model_validate({**request, "promotion_authorized": True})


def test_external_declaration_maps_to_canonical_plan_type(tmp_path: Path) -> None:
    package, request, observed = _fixture(tmp_path, external=True)
    passed = asyncio.run(
        check_local_quality(package, {**request, "calibration": observed}, assessment=_assessment(package))
    )
    assert passed.status == "local_checks_passed", passed
    assert passed.stages[-3].receipt.scorer_type == "external"


@pytest.mark.parametrize("intent", ["create", "update"])
def test_native_observed_content_and_update_capture(tmp_path: Path, intent: str) -> None:
    from test_quality_workflow import QualityFixtureReviewer

    package, request, observed = _fixture(tmp_path)
    request.update(intent=intent, content_review_mode="observed", calibration=observed)
    options = {}
    if intent == "update":
        request["update_baseline"] = request["candidate"]
        options["baseline_root"] = package
    result = asyncio.run(
        check_local_quality(package, request, adapter=QualityFixtureReviewer(_assessment(package)), **options)
    )
    assert result.status == "local_checks_passed"
    assert result.stages[-1].receipt.schema_version == "content-review-execution/v1"
    assert (result.baseline_final_capture is not None) == (intent == "update")
    assert NativeLocalCheckResult.model_validate_json(result.model_dump_json()) == result


def test_native_final_recapture_rejects_changed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from skills_sdk.evaluation import quality_workflow as workflow

    package, request, observed = _fixture(tmp_path)
    request["calibration"] = observed
    review = _assessment(package)
    original = workflow.assess_content_review
    entrypoint = package / "SKILL.md"
    before = entrypoint.read_bytes()

    def change_after_review(root: Path, *, source_revision: str, assessment: object) -> object:
        result = original(root, source_revision=source_revision, assessment=assessment)
        entrypoint.write_bytes(before + b"\nChanged.\n")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(workflow, "assess_content_review", change_after_review)
        result = asyncio.run(check_local_quality(package, request, assessment=review))
    assert result.blocked_stage == "final-capture"
    entrypoint.write_bytes(before)
    assert asyncio.run(check_local_quality(package, request, assessment=review)).status == "local_checks_passed"


def test_native_result_retains_the_selected_observation(tmp_path: Path) -> None:
    package, request, observed = _fixture(tmp_path)
    passed = asyncio.run(
        check_local_quality(package, {**request, "calibration": observed}, assessment=_assessment(package))
    )
    raw = passed.model_dump(mode="json")
    raw["request"]["calibration"]["results"][0]["judge_result_sha256"] = "a" * 64
    with pytest.raises(ValidationError, match="frozen calibration plan"):
        NativeLocalCheckResult.model_validate(raw)
