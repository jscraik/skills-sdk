"""Retained evidence must describe a reachable first-stop quality workflow."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_quality_workflow import _assessment, _package_path, _request

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import check_local_quality
from skills_sdk.models import LocalCheckResultV2


@pytest.mark.parametrize("stage", ["intake", "validate", "scenario-coverage", "scorer-quality", "scorer-calibration"])
def test_missing_input_cannot_stop_input_independent_stage(tmp_path: Path, stage: str) -> None:
    """Reject impossible missing-input stops, retaining genuine missing-content recovery."""
    request = _request(tmp_path)
    package = _package_path(tmp_path)
    passed = asyncio.run(check_local_quality(package, request, assessment=_assessment(package)))
    forged = passed.model_dump(mode="json")
    index = next(index for index, item in enumerate(forged["stages"]) if item["name"] == stage)
    forged["stages"] = forged["stages"][:index]
    forged.update(
        status="blocked",
        blocked_stage=stage,
        blocker={"code": "quality_input_missing", "message": "Missing input."},
        final_capture=None,
        baseline_final_capture=None,
    )
    if not forged["stages"]:
        forged["applied_policy"] = None
    with pytest.raises(ValidationError, match="input-dependent"):
        LocalCheckResultV2.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("local-check.v2", forged)
    missing = asyncio.run(check_local_quality(package, {**request, "content_review_mode": "observed"}))
    assert missing.blocked_stage == "content-review"
    assert missing.blocker is not None and missing.blocker.code == "quality_input_missing"
    SchemaRegistry().validate("local-check.v2", missing.model_dump(mode="json"))
    SchemaRegistry().validate("local-check.v2", passed.model_dump(mode="json"))


@pytest.mark.parametrize(
    "code", ["quality_final_capture_changed", "quality_candidate_changed", "quality_input_missing", "unrelated_failure"]
)
def test_request_failure_requires_request_blocker_code(tmp_path: Path, code: str) -> None:
    """Reject unrelated recovery codes in an otherwise valid pre-request blocker."""
    request = _request(tmp_path)
    package = _package_path(tmp_path)
    invalid = asyncio.run(check_local_quality(package, {}))
    forged = invalid.model_dump(mode="json")
    forged["blocker"]["code"] = code
    with pytest.raises(ValidationError, match="request blocker code"):
        LocalCheckResultV2.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("local-check.v2", forged)
    for allowed in ("invalid_quality_request", "unexpected_quality_baseline", "invalid_quality_input"):
        corrected = invalid.model_dump(mode="json")
        corrected["blocker"]["code"] = allowed
        SchemaRegistry().validate("local-check.v2", corrected)
    recovered = asyncio.run(check_local_quality(package, request, assessment=_assessment(package)))
    assert recovered.status == "local_checks_passed"


@pytest.mark.parametrize(
    ("capture", "defect"),
    [
        ("baseline", "missing"),
        ("baseline", "package"),
        ("baseline", "revision"),
        ("current", "package"),
        ("current", "revision"),
    ],
)
def test_failed_update_final_capture_retains_bound_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture: str, defect: str
) -> None:
    """Even a failed current capture must retain the selected baseline observation."""
    from skills_sdk.evaluation import quality_workflow as workflow

    request = _request(tmp_path, "update")
    package = _package_path(tmp_path)
    baseline = tmp_path / "baseline" / package.name
    shutil.copytree(package, baseline)
    request["update_baseline"] = dict(request["candidate"])
    original = workflow.assess_content_review
    entrypoint = package / "SKILL.md"
    original_bytes = entrypoint.read_bytes()

    def change_after_review(root: Path, *, source_revision: str, assessment: object) -> object:
        receipt = original(root, source_revision=source_revision, assessment=assessment)
        entrypoint.write_bytes(original_bytes + b"\nChanged after review.\n")
        return receipt

    with monkeypatch.context() as patch:
        patch.setattr(workflow, "assess_content_review", change_after_review)
        blocked = asyncio.run(
            workflow.check_local_quality(package, request, baseline_root=baseline, assessment=_assessment(package))
        )
    assert blocked.blocked_stage == "final-capture"
    assert blocked.baseline_final_capture is not None
    forged = blocked.model_dump(mode="json")
    key = "baseline_final_capture" if capture == "baseline" else "final_capture"
    if defect == "missing":
        forged[key] = None
    else:
        field = "package_id" if defect == "package" else "source_revision"
        forged[key]["candidate"][field] = "other-package" if defect == "package" else "2" * 40
        if defect == "package":
            forged[key]["identity"].update(package_id="other-package", name="other-package")
    with pytest.raises(ValidationError, match=f"final {capture} capture"):
        LocalCheckResultV2.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("local-check.v2", forged)
    SchemaRegistry().validate("local-check.v2", blocked.model_dump(mode="json"))
    entrypoint.write_bytes(original_bytes)
    recovered = asyncio.run(
        workflow.check_local_quality(package, request, baseline_root=baseline, assessment=_assessment(package))
    )
    assert recovered.status == "local_checks_passed"


@pytest.mark.parametrize(
    ("intent", "capture"),
    [("create", "final_capture"), ("update", "final_capture"), ("update", "baseline_final_capture")],
)
def test_candidate_change_forbids_downstream_captures(tmp_path: Path, intent: str, capture: str) -> None:
    """Reject captures after a last-stage candidate mismatch and accept capture-free recovery."""
    request = _request(tmp_path, intent)
    package = _package_path(tmp_path)
    if intent == "update":
        request["update_baseline"] = dict(request["candidate"])
    passed = asyncio.run(
        check_local_quality(
            package, request, baseline_root=package if intent == "update" else None, assessment=_assessment(package)
        )
    )
    valid = passed.model_dump(mode="json")
    receipt = valid["stages"][-1]["receipt"]
    receipt["candidate"]["content_sha256"] = "1" * 64
    receipt["assessment"]["candidate"] = dict(receipt["candidate"])
    receipt["assessment"]["evidence"][0]["sha256"] = "1" * 64
    valid.update(
        status="blocked",
        blocked_stage="candidate_changed",
        blocker={"code": "quality_candidate_changed", "message": "Candidate changed."},
        final_capture=None,
        baseline_final_capture=None,
    )
    SchemaRegistry().validate("local-check.v2", valid)
    forged = json.loads(json.dumps(valid))
    forged[capture] = passed.final_capture.model_dump(mode="json")
    with pytest.raises(ValidationError, match="final captures"):
        LocalCheckResultV2.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("local-check.v2", forged)
    SchemaRegistry().validate("local-check.v2", valid)
    SchemaRegistry().validate("local-check.v2", passed.model_dump(mode="json"))
