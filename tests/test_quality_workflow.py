"""Intent and policy ingress for the additive candidate-bound quality journey."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_local_check_cli import REVISION, _fixture

from skills_sdk.cli.main import main
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.content_review import ContentReviewInput
from skills_sdk.evaluation.quality_workflow import check_local_quality
from skills_sdk.models.quality_workflow import LocalCheckRequestV2, LocalCheckResultV2
from skills_sdk.models.safety import PackageSafetyReviewer
from skills_sdk.validation import validate_skill_package


def _request(root: Path, intent: str = "create") -> dict[str, object]:
    """Bind a portable request to the synthetic package's actual captured bytes."""
    package, context = _fixture(root)
    candidate = validate_skill_package(package, source_revision=REVISION).candidate
    assert candidate is not None
    identity = candidate.model_dump(mode="json")
    return {
        "schema_version": "local-check-request/v2",
        "intent": intent,
        "candidate": identity,
        "intake": json.loads(context.read_text(encoding="utf-8")),
        "policy": {"required_files": ["references/evals.yaml"], "check_reference_content": True},
        "coverage_plan": {
            "candidate": identity,
            "scenario_set_id": "active-ten",
            "claims": [{"id": "bounded-output", "statement": "Returns a bounded result."}],
            "mappings": [{"claim_id": "bounded-output", "case_ids": ["case-0"]}],
        },
        "content_review_mode": "supplied",
    }


@pytest.mark.parametrize("intent", ["create", "external-check"])
def test_request_preserves_explicit_intent_and_policy(tmp_path: Path, intent: str) -> None:
    request = LocalCheckRequestV2.model_validate(_request(tmp_path, intent))
    assert request.intent == intent
    assert request.policy.required_files == ("references/evals.yaml",)
    assert request.policy.check_reference_content is True
    assert request.update_baseline is None


def test_update_requires_same_package_baseline_and_accepts_noop(tmp_path: Path) -> None:
    payload = _request(tmp_path, "update")
    with pytest.raises(ValidationError, match="update baseline"):
        LocalCheckRequestV2.model_validate(payload)
    candidate = dict(payload["candidate"])
    unchanged = LocalCheckRequestV2.model_validate({**payload, "update_baseline": candidate})
    assert unchanged.update_baseline == unchanged.candidate
    baseline = {**candidate, "source_revision": "2" * 40}
    request = LocalCheckRequestV2.model_validate({**payload, "update_baseline": baseline})
    assert request.update_baseline.source_revision == "2" * 40
    with pytest.raises(ValidationError, match="same package"):
        LocalCheckRequestV2.model_validate({**payload, "update_baseline": {**baseline, "package_id": "other"}})
    with pytest.raises(ValidationError, match="only update"):
        LocalCheckRequestV2.model_validate({**payload, "intent": "create", "update_baseline": baseline})


@pytest.mark.parametrize("field", ["candidate", "coverage_plan", "intake"])
def test_request_rejects_cross_candidate_context(tmp_path: Path, field: str) -> None:
    payload = _request(tmp_path)
    changed = dict(payload[field])
    if field == "coverage_plan":
        changed["candidate"] = {**changed["candidate"], "source_revision": "2" * 40}
    else:
        changed["source_revision"] = "2" * 40
    with pytest.raises(ValidationError):
        LocalCheckRequestV2.model_validate({**payload, field: changed})


@pytest.mark.parametrize(
    "policy",
    [
        {"check_reference_content": 1},
        {"required_files": ["../escape"]},
        {"required_files": ["references/evals.yaml", "references/evals.yaml"]},
        {"max_entrypoint_lines": True},
        {"max_reference_depth": -1},
        {"unknown": True},
    ],
)
def test_request_rejects_malformed_policy(tmp_path: Path, policy: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LocalCheckRequestV2.model_validate({**_request(tmp_path), "policy": policy})


def test_forged_typed_request_is_revalidated(tmp_path: Path) -> None:
    request = LocalCheckRequestV2.model_validate(_request(tmp_path))
    forged = request.model_copy(update={"intent": "update"})
    with pytest.raises(ValidationError, match="update baseline"):
        LocalCheckRequestV2.model_validate(forged)


def test_registry_and_schema_reject_missing_update_baseline(tmp_path: Path) -> None:
    payload = _request(tmp_path)
    registry = SchemaRegistry()
    schema = Draft202012Validator(registry.load("local-check-request.v2"))
    registry.validate("local-check-request.v2", payload)
    assert schema.is_valid(payload)
    rejected = {**payload, "intent": "update"}
    assert not schema.is_valid(rejected)
    with pytest.raises(ContractError):
        registry.validate("local-check-request.v2", rejected)
    registry.validate("local-check-request.v2", payload)


def test_byte_text_and_streaming_policy_fail_before_consumption(tmp_path: Path) -> None:
    payload = _request(tmp_path)
    with pytest.raises(ValidationError, match="JSON text"):
        LocalCheckRequestV2.model_validate({**payload, "intent": b"create"})
    consumed: list[str] = []

    def paths() -> object:
        consumed.append("called")
        yield "references/evals.yaml"

    with pytest.raises(ValidationError):
        LocalCheckRequestV2.model_validate({**payload, "policy": {"required_files": paths()}})
    assert consumed == []


def _assessment(package: Path) -> dict[str, object]:
    """Supply synthetic manual evidence, not an assertion of semantic accuracy."""
    validation = validate_skill_package(package, source_revision=REVISION)
    assert validation.candidate is not None
    ids = {item.path: f"file-{index}" for index, item in enumerate(validation.files)}
    dimensions = [("description", "SKILL.md"), ("progressive_disclosure", "SKILL.md")]
    dimensions.extend(("reference", path) for path in ids if path.startswith("references/"))
    return {
        "candidate": validation.candidate.model_dump(mode="json"),
        "reviewer": {"adapter_id": "fixture-review", "adapter_version_or_digest": "1", "method": "manual_review"},
        "evidence": [
            {"evidence_id": ids[item.path], "kind": "manual_review", "ref": item.path, "sha256": item.sha256}
            for item in validation.files
        ],
        "items": [
            {
                "dimension": dimension,
                "path": path,
                "status": "clear",
                "rationale": "Fixture review recorded.",
                "evidence_ids": [ids[path]],
            }
            for dimension, path in dimensions
        ],
    }


def _package_path(tmp_path: Path) -> Path:
    return next(path.parent for path in tmp_path.glob("*/SKILL.md"))


@pytest.mark.parametrize("intent", ["create", "external-check", "update"])
def test_quality_workflow_runs_ordered_checks_and_final_captures(tmp_path: Path, intent: str) -> None:
    payload = _request(tmp_path, intent)
    package = _package_path(tmp_path)
    baseline = None
    if intent == "update":
        payload["update_baseline"] = payload["candidate"]
        baseline = package
    result = asyncio.run(check_local_quality(package, payload, baseline_root=baseline, assessment=_assessment(package)))
    assert result.status == "local_checks_passed"
    names = [stage.name for stage in result.stages]
    assert names == (["baseline"] if baseline else []) + [
        "intake",
        "validate",
        "scenario-coverage",
        "scorer-quality",
        "scorer-calibration",
        "content-review",
    ]
    assert result.final_capture.candidate == result.request.candidate
    assert result.evaluation_executed is False
    assert result.promotion_authorized is False
    assert result.stages[-1].receipt.semantic_review_executed is False
    LocalCheckResultV2.model_validate_json(result.model_dump_json())


def test_quality_workflow_content_rejection_and_recovery(tmp_path: Path) -> None:
    payload = _request(tmp_path)
    package = _package_path(tmp_path)
    rejected = asyncio.run(check_local_quality(package, payload, assessment={}))
    assert rejected.status == "blocked" and rejected.blocked_stage == "content-review"
    assert len(rejected.stages) == 6
    recovered = asyncio.run(check_local_quality(package, payload, assessment=_assessment(package)))
    assert recovered.status == "local_checks_passed"
    assert recovered.stages[:-1] == rejected.stages[:-1]


def test_quality_workflow_observes_required_baseline(tmp_path: Path) -> None:
    payload = _request(tmp_path, "update")
    package = _package_path(tmp_path)
    payload["update_baseline"] = payload["candidate"]
    missing = asyncio.run(check_local_quality(package, payload))
    assert missing.blocked_stage == "baseline" and missing.stages == ()
    payload["update_baseline"] = {**payload["candidate"], "content_sha256": "0" * 64}
    stale = asyncio.run(check_local_quality(package, payload, baseline_root=package))
    assert stale.blocked_stage == "candidate_changed" and len(stale.stages) == 1
    payload["update_baseline"] = payload["candidate"]
    assert (
        asyncio.run(
            check_local_quality(package, payload, baseline_root=package, assessment=_assessment(package))
        ).status
        == "local_checks_passed"
    )


def test_quality_result_rejects_forged_stop_and_proof_flags(tmp_path: Path) -> None:
    payload = _request(tmp_path)
    package = _package_path(tmp_path)
    result = asyncio.run(check_local_quality(package, payload, assessment={}))
    with pytest.raises(ValidationError, match="first incomplete"):
        LocalCheckResultV2.model_validate(result.model_copy(update={"blocked_stage": "intake"}))
    with pytest.raises(ValidationError, match="literal false"):
        LocalCheckResultV2.model_validate(result.model_copy(update={"evaluation_executed": 0}))


def test_quality_policy_and_owned_coverage_gaps_stop_before_content(tmp_path: Path) -> None:
    payload = _request(tmp_path)
    package = _package_path(tmp_path)
    selected = {**payload, "policy": {"required_files": ["agents/openai.yaml"]}}
    blocked = asyncio.run(check_local_quality(package, selected))
    assert blocked.blocked_stage == "intake" and len(blocked.stages) == 1
    assert blocked.stages[0].receipt.validation.findings[0].code == "required_file_missing"
    plan = {
        **payload["coverage_plan"],
        "gaps": [{"id": "missing-case", "reason": "Not yet covered.", "owner": "fixture"}],
        "mappings": [{"claim_id": "bounded-output", "gap_ids": ["missing-case"]}],
    }
    gaps = asyncio.run(check_local_quality(package, {**payload, "coverage_plan": plan}))
    assert gaps.blocked_stage == "scenario-coverage" and len(gaps.stages) == 3
    assert gaps.stages[-1].receipt.status == "pass"
    assert gaps.stages[-1].receipt.coverage_complete is False
    assert (
        asyncio.run(check_local_quality(package, payload, assessment=_assessment(package))).status
        == "local_checks_passed"
    )


def test_quality_final_capture_detects_post_review_source_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skills_sdk.evaluation import quality_workflow as workflow

    payload = _request(tmp_path)
    package = _package_path(tmp_path)
    assessment = _assessment(package)
    original = workflow.assess_content_review
    entrypoint = package / "SKILL.md"
    initial = entrypoint.read_bytes()

    def mutate_after_review(root: Path, *, source_revision: str, assessment: object) -> object:
        receipt = original(root, source_revision=source_revision, assessment=assessment)
        entrypoint.write_bytes(initial + b"\nChanged after review.\n")
        return receipt

    with monkeypatch.context() as patch:
        patch.setattr(workflow, "assess_content_review", mutate_after_review)
        changed = asyncio.run(workflow.check_local_quality(package, payload, assessment=assessment))
    assert changed.blocked_stage == "final-capture"
    assert all(stage.passed() for stage in changed.stages)
    assert changed.final_capture.candidate != changed.request.candidate
    entrypoint.write_bytes(initial)
    assert (
        asyncio.run(workflow.check_local_quality(package, payload, assessment=assessment)).status
        == "local_checks_passed"
    )


class QualityFixtureReviewer:
    """Return fixture-only per-document evidence from an actually observed callback."""

    reviewer = PackageSafetyReviewer(adapter_id="fixture-review", adapter_version_or_digest="1", method="manual_review")

    def __init__(self, assessment: dict[str, object]) -> None:
        self.assessment = assessment

    async def review(self, inputs: ContentReviewInput) -> object:
        assert self.assessment["candidate"] == inputs.candidate.model_dump(mode="json")
        return self.assessment


def test_quality_observed_lane_requires_and_records_callback(tmp_path: Path) -> None:

    payload = {**_request(tmp_path), "content_review_mode": "observed"}
    package = _package_path(tmp_path)
    missing = asyncio.run(check_local_quality(package, payload))
    assert missing.blocked_stage == "content-review" and len(missing.stages) == 5
    adapter = QualityFixtureReviewer(_assessment(package))
    observed = asyncio.run(check_local_quality(package, payload, adapter=adapter))
    assert observed.status == "local_checks_passed", observed.model_dump_json()
    assert observed.stages[-1].receipt.adapter_invoked is True
    assert observed.evaluation_executed is False
    contradicted = asyncio.run(check_local_quality(package, payload, adapter=adapter, assessment={}))
    assert contradicted.blocked_stage == "content-review" and len(contradicted.stages) == 5


def test_quality_cli_accepts_rejects_recovers_and_emits_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _request(tmp_path)
    package = _package_path(tmp_path)
    request = tmp_path / "request.json"
    assessment = tmp_path / "assessment.json"
    request.write_text(json.dumps(payload))
    assessment.write_text(json.dumps(_assessment(package)))
    command = [
        "check-quality",
        str(package),
        "--request",
        str(request),
        "--assessment",
        str(assessment),
        "--json",
        "--robot",
    ]
    assert main(command) == 0
    accepted = json.loads(capsys.readouterr().out)
    SchemaRegistry().validate("local-check.v2", accepted)
    assessment.write_text("{}")
    assert main(command) == 2
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["blocked_stage"] == "content-review"
    assessment.write_text(json.dumps(_assessment(package)))
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out) == accepted
    assert main(command[:-2]) == 0
    assert "local_checks_passed" in capsys.readouterr().out


def test_quality_cli_rejects_duplicate_members_and_symlinks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _request(tmp_path)
    package = _package_path(tmp_path)
    request = tmp_path / "request.json"
    request.write_text('{"intent":"create","intent":"update"}')
    command = ["check-quality", str(package), "--request", str(request), "--json"]
    assert main(command) == 2
    assert json.loads(capsys.readouterr().out)["blocked_stage"] == "request"
    request.write_text(json.dumps(payload))
    link = tmp_path / "request-link.json"
    link.symlink_to(request)
    assert main(["check-quality", str(package), "--request", str(link), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["request"] is None


@pytest.mark.parametrize("stop", ["owner", "policy", "review"])
def test_quality_cli_text_explains_stage_receipt(tmp_path: Path, capsys: pytest.CaptureFixture[str], stop: str) -> None:
    payload = _request(tmp_path)
    if stop == "owner":
        payload["intake"]["checks"]["owner_unchanged"] = False
        expected = ("decision: needs_owner_decision", "decision_blocker: owner_decision_required")
    elif stop == "policy":
        payload["policy"] = {"required_files": ["agents/openai.yaml"]}
        expected = (
            "decision_blocker: required_file_missing",
            "required_file_missing: selected policy requires a readable regular file",
        )
    else:
        expected = ("invalid_content_review: supplied review must match the closed assessment contract",)
    request = tmp_path / "request.json"
    request.write_text(json.dumps(payload))
    assert main(["check-quality", str(_package_path(tmp_path)), "--request", str(request)]) == 2
    output = capsys.readouterr().out
    assert "quality_stage_incomplete:" in output
    for detail in expected:
        assert f"  {detail}\n" in output
    if stop == "policy":
        assert output.count(f"  {expected[1]}\n") == 2  # Validation finding and receipt blocker.


@pytest.mark.parametrize("stop", ["request", "baseline", "candidate_changed", "content-review"])
def test_quality_cli_text_excludes_unrelated_receipts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], stop: str
) -> None:
    payload = _request(tmp_path)
    if stop == "request":
        payload = {}
    elif stop == "baseline":
        payload.update(intent="update", update_baseline=payload["candidate"])
    elif stop == "candidate_changed":
        candidate = {**payload["candidate"], "content_sha256": "0" * 64}
        payload["candidate"] = payload["coverage_plan"]["candidate"] = candidate
    else:
        payload["content_review_mode"] = "observed"
    request = tmp_path / "request.json"
    request.write_text(json.dumps(payload))
    assert main(["check-quality", str(_package_path(tmp_path)), "--request", str(request)]) == 2
    output = capsys.readouterr().out.splitlines()
    assert output[0] == "check-quality: blocked"
    assert output[1].startswith(f"  {stop}: ")
    assert len(output) == 2


def test_update_final_capture_detects_baseline_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    from skills_sdk.evaluation import quality_workflow as workflow

    payload = _request(tmp_path, "update")
    package = _package_path(tmp_path)
    baseline = tmp_path / "baseline" / "synthetic-skill"
    shutil.copytree(package, baseline)
    payload["update_baseline"] = payload["candidate"]
    original = workflow.assess_content_review

    def mutate_baseline(root: Path, *, source_revision: str, assessment: object) -> object:
        receipt = original(root, source_revision=source_revision, assessment=assessment)
        (baseline / "SKILL.md").write_text("---\nname: synthetic-skill\ndescription: Changed baseline.\n---\n")
        return receipt

    with monkeypatch.context() as patch:
        patch.setattr(workflow, "assess_content_review", mutate_baseline)
        changed = asyncio.run(
            workflow.check_local_quality(package, payload, baseline_root=baseline, assessment=_assessment(package))
        )
    assert changed.blocked_stage == "final-capture"
    assert changed.final_capture.candidate == changed.request.candidate
    assert changed.baseline_final_capture.candidate != changed.request.update_baseline
    (baseline / "SKILL.md").write_bytes((package / "SKILL.md").read_bytes())
    assert (
        asyncio.run(
            workflow.check_local_quality(package, payload, baseline_root=baseline, assessment=_assessment(package))
        ).status
        == "local_checks_passed"
    )


def test_standalone_stage_and_result_revalidate_forged_receipts(tmp_path: Path) -> None:
    from skills_sdk.models.quality_workflow import LocalQualityStage

    payload = _request(tmp_path)
    package = _package_path(tmp_path)
    result = asyncio.run(check_local_quality(package, payload, assessment=_assessment(package)))
    validate = result.stages[1]
    forged = validate.model_copy(update={"receipt": validate.receipt.model_copy(update={"status": "blocked"})})
    with pytest.raises(ValidationError):
        LocalQualityStage.model_validate(forged)
    with pytest.raises(ValidationError):
        LocalCheckResultV2.model_validate(result.model_copy(update={"stages": (result.stages[0], forged)}))
    with pytest.raises(ValidationError, match="unchanged final captures"):
        LocalCheckResultV2.model_validate(result.model_copy(update={"final_capture": None}))
    SchemaRegistry().validate("local-check.v2", result.model_dump(mode="json"))


@pytest.mark.parametrize("target", ["final_capture", "baseline_final_capture", "baseline", "validate"])
def test_quality_capture_rejects_manifest_digest_contradictions_and_recovers(tmp_path: Path, target: str) -> None:
    payload = _request(tmp_path, "update")
    package = _package_path(tmp_path)
    payload["update_baseline"] = payload["candidate"]
    result = asyncio.run(check_local_quality(package, payload, baseline_root=package, assessment=_assessment(package)))
    accepted = result.model_dump(mode="json")
    capture = (
        accepted[target]
        if target.endswith("capture")
        else next(stage["receipt"] for stage in accepted["stages"] if stage["name"] == target)
    )
    capture["files"][0]["sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="digest must match"):
        LocalCheckResultV2.model_validate(accepted)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("local-check.v2", accepted)
    SchemaRegistry().validate("local-check.v2", result.model_dump(mode="json"))
    if target.endswith("capture"):
        original = getattr(result, target)
        forged = original.model_copy(
            update={"files": (original.files[0].model_copy(update={"sha256": "0" * 64}), *original.files[1:])}
        )
        with pytest.raises(ValidationError, match="digest must match"):
            LocalCheckResultV2.model_validate(result.model_copy(update={target: forged}))


def test_quality_review_subclass_rejected_before_serializer_and_recovers(tmp_path: Path) -> None:
    from collections import UserDict

    from skills_sdk.models.content_review import ContentReviewResult

    calls = []

    class CustomReview(ContentReviewResult):
        def model_dump(self, **kwargs: object) -> dict[str, object]:
            calls.append("called")
            raise RuntimeError("private diagnostic")

    payload = _request(tmp_path)
    package = _package_path(tmp_path)
    result = asyncio.run(check_local_quality(package, payload, assessment=_assessment(package)))
    content = result.stages[-1]
    custom = CustomReview.model_construct(**dict(content.receipt))
    forged = result.model_copy(update={"stages": (*result.stages[:-1], content.model_copy(update={"receipt": custom}))})
    with pytest.raises(ValidationError, match="canonical review"):
        LocalCheckResultV2.model_validate(UserDict(dict(forged)))
    assert calls == []
    assert LocalCheckResultV2.model_validate(result).status == "local_checks_passed"
