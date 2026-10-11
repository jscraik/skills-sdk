"""Repeated and blocked validation observations must retain coherent evidence."""

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
from skills_sdk.evaluation import quality_workflow as workflow
from skills_sdk.models import LocalCheckResultV2


def _capture(result: dict[str, object], location: str) -> dict[str, object]:
    """Select a serialized validation observation without altering sibling evidence."""
    if location in {"final_capture", "baseline_final_capture"}:
        return result[location]
    stage = next(item for item in result["stages"] if item["name"] == location)
    return stage["receipt"]


def _reject_and_recover(forged: dict[str, object], original: LocalCheckResultV2, message: str) -> None:
    """Reject raw, copied typed and registry inputs, then accept the actual receipt."""
    with pytest.raises(ValidationError, match=message):
        LocalCheckResultV2.model_validate(forged)
    with pytest.raises(ValidationError, match=message):
        LocalCheckResultV2.model_validate(LocalCheckResultV2.model_construct(**forged))
    with pytest.raises(ContractError):
        SchemaRegistry().validate("local-check.v2", forged)
    LocalCheckResultV2.model_validate(original)
    SchemaRegistry().validate("local-check.v2", original.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("location", "field"),
    [("baseline", "package")]
    + [
        (location, field)
        for location in ("final_capture", "baseline_final_capture")
        for field in ("package", "version", "role", "size")
    ],
)
def test_blocked_capture_identity_binds_candidate_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str, field: str
) -> None:
    """Retain actual symlink blockers while rejecting a contradictory package identity."""
    request = _request(tmp_path, "update")
    package = _package_path(tmp_path)
    baseline = tmp_path / "baseline" / package.name
    shutil.copytree(package, baseline)
    request["update_baseline"] = dict(request["candidate"])
    target = package if location == "final_capture" else baseline
    unsafe = target / "unsafe-link"
    original_review = workflow.assess_content_review

    def add_symlink_after_review(root: Path, *, source_revision: str, assessment: object) -> object:
        receipt = original_review(root, source_revision=source_revision, assessment=assessment)
        unsafe.symlink_to(target / "SKILL.md")
        return receipt

    if location == "baseline":
        unsafe.symlink_to(target / "SKILL.md")
        blocked = asyncio.run(
            workflow.check_local_quality(package, request, baseline_root=baseline, assessment=_assessment(package))
        )
        assert blocked.blocked_stage == "baseline"
    else:
        with monkeypatch.context() as patch:
            patch.setattr(workflow, "assess_content_review", add_symlink_after_review)
            blocked = asyncio.run(
                workflow.check_local_quality(package, request, baseline_root=baseline, assessment=_assessment(package))
            )
        assert blocked.blocked_stage == "final-capture"
    forged = blocked.model_dump(mode="json")
    capture = _capture(forged, location)
    assert capture["status"] == "blocked" and capture["candidate"] is not None and capture["identity"] is not None
    if field == "package":
        capture["identity"].update(package_id="other-package", name="other-package")
    elif field == "version":
        capture["identity"]["version"] = "changed-version"
    elif field == "role":
        capture["files"][0]["role"] = "asset"
    else:
        capture["files"][0]["size_bytes"] += 1
    _reject_and_recover(forged, blocked, "capture identity" if field == "package" else "repeated validation")
    unsafe.unlink()
    recovered = asyncio.run(
        workflow.check_local_quality(package, request, baseline_root=baseline, assessment=_assessment(package))
    )
    assert recovered.status == "local_checks_passed"


@pytest.mark.parametrize("location", ["validate", "final_capture", "baseline", "baseline_final_capture"])
@pytest.mark.parametrize("field", ["version", "role", "size", "findings"])
def test_unchanged_repeated_validations_agree_and_recover(tmp_path: Path, location: str, field: str) -> None:
    """Reject metadata differences omitted from candidate content identity hashing."""
    request = _request(tmp_path, "update")
    package = _package_path(tmp_path)
    request["update_baseline"] = dict(request["candidate"])
    passed = asyncio.run(
        workflow.check_local_quality(package, request, baseline_root=package, assessment=_assessment(package))
    )
    forged = json.loads(passed.model_dump_json())
    capture = _capture(forged, location)
    if field == "version":
        capture["identity"]["version"] = "changed-version"
    elif field == "role":
        capture["files"][0]["role"] = "asset"
    elif field == "size":
        capture["files"][0]["size_bytes"] += 1
    else:
        capture["findings"].append(
            {"code": "invented_warning", "severity": "warning", "message": "Invented warning.", "evidence_refs": []}
        )
    _reject_and_recover(forged, passed, "repeated validation")
