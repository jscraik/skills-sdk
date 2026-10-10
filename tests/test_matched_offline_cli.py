"""Controlled offline CLI observes callbacks, rejects input and recovers."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from test_matched_calibration import _dimensions
from test_matched_comparison import _plan
from test_matched_execution import _matched
from test_matched_handoff import _journey
from test_provider_call import _provider_request
from test_selected_case_evaluation import _evidence

from skills_sdk.cli.main import main
from skills_sdk.cli.matched_offline import _FixtureProvider
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import prepare_matched_cloud_handoff
from skills_sdk.models.matched_comparison import MatchedComparisonPlan, MatchedVariantJudgment
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.providers import DEFAULT_PROVIDER_CALL_LIMITS, execute_provider_call


@pytest.mark.parametrize("provider_mode", ["complete", "stream"])
@pytest.mark.parametrize(
    "text", ["", "a" * 16_385, "\U0001f642" * 4_097], ids=["empty", "ascii-chunks", "unicode-chunks"]
)
def test_offline_provider_preserves_output_evidence_and_cleanup(
    provider_mode: str, text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def wrong_mode(*args: object) -> object:
        raise AssertionError("the descriptor selected the other provider protocol")

    monkeypatch.setattr(_FixtureProvider, "complete" if provider_mode == "stream" else "stream", wrong_mode)
    request = _provider_request()
    adapter = _FixtureProvider(
        TextProviderAdapterDescriptor(provider=request.provider, mode=provider_mode),
        _plan().lanes[0].generator_parameters,
        text,
        ("evidence/provider-result.json",),
    )
    result = asyncio.run(execute_provider_call(request, None, adapter))
    assert result.complete_text == text
    public = result.public_result
    assert public.status == "completed" and public.mode == provider_mode
    assert public.output_bytes == len(text.encode("utf-8"))
    assert public.output_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert public.cleanup_attempted and public.cleanup_succeeded
    assert public.execution.evidence_refs == ("evidence/provider-result.json",)
    if provider_mode == "stream" and text:
        assert public.event_count > 2 and public.max_inflight_pulls == 1


@pytest.mark.parametrize("provider_mode", ["complete", "stream"])
def test_offline_provider_output_limit_rejects_then_recovers(provider_mode: str) -> None:
    request = _provider_request()
    for text, rejected in (("a" * (DEFAULT_PROVIDER_CALL_LIMITS.output_bytes + 1), True), ("recovered", False)):
        adapter = _FixtureProvider(
            TextProviderAdapterDescriptor(provider=request.provider, mode=provider_mode),
            _plan().lanes[0].generator_parameters,
            text,
            ("evidence/provider-result.json",),
        )
        if rejected:
            with pytest.raises(ContractError, match=r"^provider_output_too_large:"):
                asyncio.run(execute_provider_call(request, None, adapter))
        else:
            result = asyncio.run(execute_provider_call(request, None, adapter))
            assert result.public_result.status == "completed"
            assert result.public_result.cleanup_attempted and result.public_result.cleanup_succeeded
            assert result.complete_text == text


def test_offline_trial_allocation_rejects_unbounded_fixture_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skills_sdk.cli import matched_offline

    plan, _calibrations, batch, _events = _matched(tmp_path)
    payload = _variant(batch[0].baseline, plan.rubric)
    payload["provider"]["parameters"]["trial_count"] = 10**9

    def unexpected_adapter(*args: object, **kwargs: object) -> object:
        raise AssertionError("unbounded trial input reached adapter allocation")

    monkeypatch.setattr(matched_offline, "_FixtureProvider", unexpected_adapter)
    with pytest.raises(ValueError, match="trial allocation"):
        matched_offline._variant(payload, matched=True)


def _variant(item: object, rubric: object, provider_mode: str | None = None) -> dict[str, object]:
    judgment = MatchedVariantJudgment(
        evidence=_evidence(item.definition, item.request, item.provider.text),
        confidence="medium",
        dimensions=tuple(
            {
                "dimension_id": dimension.dimension_id,
                "score": item.judge.score,
                "rationale": "Retained evidence supports this judgment.",
                "evidence_refs": ["evidence/assertion-review.json"],
            }
            for dimension in rubric.dimensions
        ),
    )
    result = {
        "package_root": str(item.definition._package_root),
        "source_revision": item.request.candidate.source_revision,
        "case_id": item.request.case_id,
        "request": item.request.model_dump(mode="json"),
        "input_payload": item.inputs.payload,
        "safety_evidence": item.inputs.safety_evidence.model_dump(mode="json"),
        "provider": {
            "descriptor": item.provider.descriptor.model_dump(mode="json"),
            "parameters": item.judge.parameters.model_dump(mode="json"),
            "output_text": item.provider.text,
            "evidence_refs": ["evidence/provider-result.json"],
        },
        "judge": {
            "identity": item.judge.identity.model_dump(mode="json"),
            "parameters": item.judge.parameters.model_dump(mode="json"),
            "judgment": judgment.model_dump(mode="json"),
        },
    }
    if provider_mode is not None:
        result["provider"]["descriptor"]["mode"] = provider_mode
    context = getattr(item, "plugin_context", None)
    if context is not None:
        result["plugin_context"] = {
            "root": str(context.root),
            "validation": context.validation.model_dump(mode="json"),
            "driver_skill_path": context.driver_skill_path,
            "selected_skill_paths": list(context.selected_skill_paths),
            "reference_paths": list(context.reference_paths),
            "policy": (context.policy or context.validation.policy).model_dump(mode="json"),
            "safety_evidence": context.safety_evidence.model_dump(mode="json"),
        }
    return result


def _mode_plan(plan: MatchedComparisonPlan, provider_mode: str, lane: str) -> MatchedComparisonPlan:
    """Declare the intended protocol before generating any callback observations."""
    raw = plan.model_dump(mode="json")
    for specification in raw["lanes"]:
        if specification["lane"] == lane:
            specification["generator_mode"] = provider_mode
    return MatchedComparisonPlan.model_validate(raw)


@pytest.mark.parametrize("children,provider_mode", [(1, "complete"), (2, "complete"), (9, "complete"), (2, "stream")])
def test_offline_local_cli_whole_batch_rejection_and_recovery(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], children: int, provider_mode: str
) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path, child_count=children)
    plan = _mode_plan(plan, provider_mode, "local")
    pairs = _pairs(batch, plan.rubric, provider_mode)
    payload = {
        "plan": plan.model_dump(mode="json"),
        "calibrations": [item.model_dump(mode="json") for item in calibrations],
        "executions": pairs,
    }
    source = tmp_path / "execution.json"
    command = ["eval", "matched-local", "--input", str(source), "--adapter-mode", "supplied-offline", "--json"]
    for data, expected in ((dict(payload, executions=pairs[:-1]), 2), (payload, 0)):
        source.write_text(json.dumps(data))
        assert main(command) == expected
        receipt = json.loads(capsys.readouterr().out)
        SchemaRegistry().validate("matched-execution.v1", receipt)
        assert receipt["provider_invocation_count"] == (0 if expected else 40)
        assert receipt["judge_invocation_count"] == (0 if expected else 40)
        assert receipt["external_authenticity_verified"] is False


@pytest.mark.parametrize("provider_mode", ["complete", "stream"])
def test_offline_dimensional_calibration_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], provider_mode: str
) -> None:
    plan, batch, _ = _dimensions(tmp_path)
    rubric = _plan().rubric
    source = tmp_path / "calibration.json"
    payload = {
        "plan": plan.model_dump(mode="json"),
        "rubric": rubric.model_dump(mode="json"),
        "executions": [_variant(item, rubric, provider_mode) for item in batch],
    }
    command = ["eval", "matched-calibration", "--input", str(source), "--adapter-mode", "supplied-offline", "--json"]
    for data, expected in ((dict(payload, extra=True), 2), (payload, 0)):
        source.write_text(json.dumps(data))
        assert main(command) == expected
        receipt = json.loads(capsys.readouterr().out)
        SchemaRegistry().validate("matched-calibration.v1", receipt)
        assert receipt["status"] == ("blocked" if expected else "pass")
        if not expected:
            assert receipt["calibration"]["judge_invocation_count"] == 6


def test_relative_plugin_host_paths_use_same_bound_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installed command contract accepts ordinary relative host source paths."""
    plan, calibrations, batch, _ = _matched(tmp_path)
    pairs = _pairs(batch, plan.rubric)
    for pair in pairs:
        for variant in pair.values():
            variant["package_root"] = str(Path(variant["package_root"]).relative_to(tmp_path))
            context = variant["plugin_context"]
            context["root"] = str(Path(context["root"]).relative_to(tmp_path))
    source = tmp_path / "relative.json"
    source.write_text(
        json.dumps(
            {
                "plan": plan.model_dump(mode="json"),
                "calibrations": [item.model_dump(mode="json") for item in calibrations],
                "executions": pairs,
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    assert main(["eval", "matched-local", "--input", source.name, "--adapter-mode", "supplied-offline", "--json"]) == 0
    raw = capsys.readouterr().out
    assert str(tmp_path) not in raw
    receipt = json.loads(raw)
    assert receipt["status"] == "completed" and receipt["provider_invocation_count"] == 40


@pytest.mark.parametrize(
    "command,schema",
    [
        ("matched-cloud", "matched-cloud-execution.v1"),
        ("matched-regression", "matched-regression.v1"),
        ("matched-cloud-regression", "matched-cloud-regression.v1"),
    ],
)
def test_offline_remaining_routes_reject_malformed_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str, schema: str
) -> None:
    source = tmp_path / "bad.json"
    source.write_text('{"duplicate":1,"duplicate":2}')
    assert main(["eval", command, "--input", str(source), "--adapter-mode", "supplied-offline", "--json"]) == 2
    receipt = json.loads(capsys.readouterr().out)
    SchemaRegistry().validate(schema, receipt)
    assert receipt["status"] == "blocked"


def _run(command: str, payload: object, root: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    source = root / "run.json"
    source.write_text(json.dumps(payload))
    assert main(["eval", command, "--input", str(source), "--adapter-mode", "supplied-offline", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def _pairs(batch: tuple[object, ...], rubric: object, provider_mode: str | None = None) -> list[dict[str, object]]:
    return [
        {
            "baseline": _variant(item.baseline, rubric, provider_mode),
            "candidate": _variant(item.candidate, rubric, provider_mode),
        }
        for item in batch
    ]


@pytest.mark.parametrize("provider_mode", ["complete", "stream"])
def test_offline_cloud_cli_retains_handoff_and_closes_regression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], provider_mode: str
) -> None:
    local, plan, calibrations, batch, _ = _journey(tmp_path)
    plan = _mode_plan(plan, provider_mode, "cloud")
    handoff = prepare_matched_cloud_handoff(local, plan)
    batch[0].candidate.provider.text = "behavior preserved; rm -rf"
    payload = {
        "handoff": handoff.model_dump(mode="json"),
        "calibrations": [item.model_dump(mode="json") for item in calibrations],
        "executions": _pairs(batch, plan.rubric, provider_mode),
    }
    failure = _run("matched-cloud", payload, tmp_path, capsys)
    SchemaRegistry().validate("matched-cloud-execution.v1", failure)
    assert failure["handoff"]["local"] == local.model_dump(mode="json")
    batch[0].candidate.provider.text = "behavior preserved"
    recovery = {
        "initial": failure,
        "assignments": [{"case_id": "case-0", "owner": "SDK maintainer"}],
        "plan": plan.model_dump(mode="json"),
        "calibrations": payload["calibrations"],
        "executions": _pairs(batch, plan.rubric, provider_mode),
    }
    closed = _run("matched-cloud-regression", recovery, tmp_path, capsys)
    SchemaRegistry().validate("matched-cloud-regression.v1", closed)
    assert closed["status"] == "closed" and closed["initial"] == failure
    assert closed["handoff"]["local"] == local.model_dump(mode="json")


@pytest.mark.parametrize("provider_mode", ["complete", "stream"])
def test_offline_local_regression_cli_retains_failure_and_rerun(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], provider_mode: str
) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path)
    plan = _mode_plan(plan, provider_mode, "local")
    batch[0].candidate.provider.text = "behavior preserved; rm -rf"
    initial = _run(
        "matched-local",
        {
            "plan": plan.model_dump(mode="json"),
            "calibrations": [item.model_dump(mode="json") for item in calibrations],
            "executions": _pairs(batch, plan.rubric, provider_mode),
        },
        tmp_path,
        capsys,
    )
    batch[0].candidate.provider.text = "behavior preserved"
    payload = {
        "initial": initial,
        "assignments": [{"case_id": "case-0", "owner": "SDK maintainer"}],
        "plan": plan.model_dump(mode="json"),
        "calibrations": [item.model_dump(mode="json") for item in calibrations],
        "executions": _pairs(batch, plan.rubric, provider_mode),
    }
    closed = _run("matched-regression", payload, tmp_path, capsys)
    SchemaRegistry().validate("matched-regression.v1", closed)
    assert closed["status"] == "closed" and closed["initial"] == initial
    assert closed["rerun"]["provider_invocation_count"] == 40
