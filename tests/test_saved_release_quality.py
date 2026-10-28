"""Saved-source representation through maintained intake and whole-plugin quality."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_plugin_quality import _plugin

from skills_sdk.cli.main import main
from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import check_plugin_quality
from skills_sdk.intake import intake_skill_package
from skills_sdk.models.intake import (
    SkillPackageIntakeContext,
    SkillPackageIntakeContextV2,
    SkillPackageIntakeReceiptV2,
)
from skills_sdk.models.plugin_quality import PluginQualityRequest, PluginQualityRequestV2, PluginQualityResultV2


def saved_request(root: Path) -> tuple[Path, dict[str, object], dict[str, object], dict[str, object]]:
    """Bind synthetic release provenance without any live provider or repository fiction."""
    plugin, request, assessments, presentation = _plugin(root)
    snapshot = {
        "schema_version": "saved-release-snapshot/v1",
        "locator": "https://example.invalid/plugins/example",
        "source_id": "example",
        "release_id": "release-one",
        "version": "1.0.0",
        "archive_sha256": "a" * 64,
        "root_candidate": request["candidate"],
        "root_mode_manifest_sha256": request["mode_manifest_sha256"],
    }
    snapshot["binding_sha256"] = canonical_json_sha256(snapshot)
    request.update(schema_version="plugin-quality-request/v2", source_snapshot=snapshot)
    for child in request["children"]:
        old = child["request"]["intake"]
        child["request"]["schema_version"] = "local-check-request/v3"
        child["request"]["intent"] = "external-check"
        child["request"]["intake"] = {
            "schema_version": "skill-package-intake-context/v2",
            "source": {
                "snapshot": deepcopy(snapshot),
                "path": child["path"],
                "candidate": child["request"]["candidate"],
            },
            "owner": old["owner"],
            "checks": old["checks"],
        }
    return plugin, request, assessments, presentation


def test_saved_release_runs_existing_quality_without_repository_field(tmp_path: Path) -> None:
    """The new family reaches all existing checks while old readers reject it."""
    root, request, assessments, presentation = saved_request(tmp_path)
    PluginQualityRequestV2.model_validate(request)
    result = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert result.status == "local_checks_passed", result.model_dump_json()
    assert result.schema_version == "plugin-quality/v2"
    intake = result.children[0].stages[0].receipt
    assert intake.schema_version == "skill-package-intake/v2"
    assert intake.source.provenance.snapshot.release_id == "release-one"
    assert "repository" not in intake.source.provenance.model_dump()
    assert "source_repository" not in intake.context.model_dump()
    assert result.release_ready is result.execution_authorized is result.evaluation_executed is False
    assert PluginQualityResultV2.model_validate(result.model_dump(mode="json")) == result
    registry = SchemaRegistry()
    payload = result.model_dump(mode="json")
    registry.validate("plugin-quality.v2", payload)
    assert Draft202012Validator(registry.load("plugin-quality.v2")).is_valid(payload)
    with pytest.raises(ValidationError):
        PluginQualityRequest.model_validate(request)


def test_saved_release_does_not_promote_unconfirmed_rights(tmp_path: Path) -> None:
    """A representable source cannot turn supplied unchecked rights into admission."""
    root, request, assessments, presentation = saved_request(tmp_path)
    request["children"][0]["request"]["intake"]["checks"]["rights"] = False
    result = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert result.status == "blocked"
    assert result.blocker.code == "plugin_quality_child_blocked"
    child = result.children[0]
    assert child.blocked_stage == "intake" and len(child.stages) == 1
    assert "rights_unconfirmed" in child.stages[0].receipt.decision.blocker_codes


@pytest.mark.parametrize("defect", ["release", "archive", "root", "mode", "child", "path", "credentials", "padding"])
def test_saved_release_rejects_changed_or_mixed_source_before_child_checks(tmp_path: Path, defect: str) -> None:
    """Frozen-source mismatches never become a child quality result."""
    root, request, _, _ = saved_request(tmp_path)
    source = request["children"][0]["request"]["intake"]["source"]
    if defect == "release":
        source["snapshot"]["release_id"] = "release-two"
    elif defect == "archive":
        source["snapshot"]["archive_sha256"] = "b" * 64
    elif defect == "root":
        source["snapshot"]["root_candidate"]["content_sha256"] = "b" * 64
    elif defect == "mode":
        source["snapshot"]["root_mode_manifest_sha256"] = "b" * 64
    elif defect == "child":
        source["candidate"] = {**source["candidate"], "content_sha256": "b" * 64}
    elif defect == "path":
        source["path"] = "skills/other"
    elif defect == "credentials":
        source["snapshot"]["locator"] = "https://user:fake@example.invalid/plugin"
    else:
        source["snapshot"]["release_id"] = " release-one "
    result = asyncio.run(check_plugin_quality(root, request))
    assert result.status == "blocked" and result.initial_capture is None and not result.children
    assert result.blocker.code == "plugin_quality_request_invalid"


def test_saved_release_stale_source_blocks_at_actual_intake(tmp_path: Path) -> None:
    """Standalone intake recaptures the child rather than accepting only the descriptor."""
    root, request, _, _ = saved_request(tmp_path)
    child = request["children"][0]
    context = SkillPackageIntakeContextV2.model_validate(child["request"]["intake"])
    target = root / child["path"] / "SKILL.md"
    target.write_text(target.read_text() + "\nChanged source.\n")
    result = intake_skill_package(root / child["path"], context)
    assert result.status == "blocked" and result.blocker.code == "saved_source_candidate_mismatch"
    assert result.execution_performed is result.network_used is result.mutation_performed is False


def test_old_intake_keeps_url_rejection(tmp_path: Path) -> None:
    """No new source interpretation leaks into the frozen v1 boundary."""
    _, request, _, _ = _plugin(tmp_path)
    context = request["children"][0]["request"]["intake"]
    context["source_repository"] = "https://example.invalid/plugins/example"
    with pytest.raises(ValidationError, match="owner/repository"):
        SkillPackageIntakeContext.model_validate(context)


@pytest.mark.parametrize("drift", ["bytes", "mode"])
def test_saved_release_changed_root_never_reaches_child(tmp_path: Path, drift: str) -> None:
    """Fresh whole-plugin capture rejects stale expected source before child work."""
    root, request, _, _ = saved_request(tmp_path)
    image = root / "assets/icon.png"
    if drift == "bytes":
        image.write_bytes(image.read_bytes() + b"changed")
    else:
        image.chmod(0o700)
    result = asyncio.run(check_plugin_quality(root, request))
    assert result.blocker.code == "plugin_quality_root_mismatch" and not result.children
    SchemaRegistry().validate("plugin-quality.v2", result.model_dump(mode="json"))


def test_saved_release_cli_accepts_representation_but_stops_unconfirmed_rights(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercise version dispatch and typed output at the maintained CLI."""
    import json

    root, request, _, _ = saved_request(tmp_path)
    request["children"][0]["request"]["intake"]["checks"]["rights"] = False
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    assert main(["check-plugin-quality", str(root), "--request", str(path), "--json", "--robot"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "plugin-quality/v2"
    assert result["blocker"]["code"] == "plugin_quality_child_blocked"
    assert result["children"][0]["blocked_stage"] == "intake"


def test_saved_source_schema_requires_semantic_fingerprint_check(tmp_path: Path) -> None:
    """Shape validation alone cannot authenticate or bind supplied provenance."""
    _, request, _, _ = saved_request(tmp_path)
    snapshot = deepcopy(request["source_snapshot"])
    snapshot["release_id"] = "other-release"
    registry = SchemaRegistry()
    assert Draft202012Validator(registry.load("saved-release-snapshot.v1")).is_valid(snapshot)
    with pytest.raises(ContractError):
        registry.validate("saved-release-snapshot.v1", snapshot)


def test_recomputed_descriptor_is_not_authenticated_release_proof(tmp_path: Path) -> None:
    """A consistent supplied descriptor cannot turn false provenance checks into true."""
    root, request, _, _ = saved_request(tmp_path)
    descriptor = request["source_snapshot"]
    descriptor["release_id"] = "other-consistent-release"
    descriptor["binding_sha256"] = canonical_json_sha256({k: v for k, v in descriptor.items() if k != "binding_sha256"})
    context = request["children"][0]["request"]["intake"]
    context["source"]["snapshot"] = deepcopy(descriptor)
    context["checks"]["provenance"] = False
    result = asyncio.run(check_plugin_quality(root, request))
    assert result.blocker.code == "plugin_quality_child_blocked"
    assert "provenance_unconfirmed" in result.children[0].stages[0].receipt.decision.blocker_codes


@pytest.mark.parametrize("defect", ["boolean", "cycle"])
def test_saved_context_revalidates_forged_instances(tmp_path: Path, defect: str) -> None:
    """Typed source contexts cannot bypass raw boolean or cycle restrictions."""
    root, request, _, _ = saved_request(tmp_path)
    child = request["children"][0]
    context = SkillPackageIntakeContextV2.model_validate(child["request"]["intake"])
    if defect == "boolean":
        forged = context.model_copy(update={"checks": context.checks.model_copy(update={"rights": "true"})})
    else:
        cycle: dict[str, object] = {}
        cycle["again"] = cycle
        forged = context.model_copy(update={"source": cycle})
    with pytest.raises(ValidationError):
        intake_skill_package(root / child["path"], forged)


def test_saved_request_revalidates_forged_snapshot(tmp_path: Path) -> None:
    """Copied typed envelopes cannot retain a changed descriptor under its old digest."""
    root, request, _, _ = saved_request(tmp_path)
    typed = PluginQualityRequestV2.model_validate(request)
    forged = typed.model_copy(
        update={"source_snapshot": typed.source_snapshot.model_copy(update={"release_id": "other"})}
    )
    result = asyncio.run(check_plugin_quality(root, forged))
    assert result.blocker.code == "plugin_quality_request_invalid" and result.initial_capture is None


def test_saved_receipt_revalidates_forged_child_capture(tmp_path: Path) -> None:
    """A typed receipt cannot substitute another captured candidate after construction."""
    root, request, _, _ = saved_request(tmp_path)
    child = request["children"][0]
    context = SkillPackageIntakeContextV2.model_validate(child["request"]["intake"])
    receipt = intake_skill_package(root / child["path"], context)
    forged = receipt.model_copy(update={"candidate": receipt.candidate.model_copy(update={"content_sha256": "b" * 64})})
    with pytest.raises(ValidationError):
        SkillPackageIntakeReceiptV2.model_validate(forged)


def test_consistent_wrong_version_stops_at_fresh_root(tmp_path: Path) -> None:
    """Even a recomputed descriptor must agree with the actual manifest version."""
    root, request, _, _ = saved_request(tmp_path)
    snapshot = request["source_snapshot"]
    snapshot["version"] = "2.0.0"
    snapshot["binding_sha256"] = canonical_json_sha256({k: v for k, v in snapshot.items() if k != "binding_sha256"})
    request["children"][0]["request"]["intake"]["source"]["snapshot"] = deepcopy(snapshot)
    result = asyncio.run(check_plugin_quality(root, request))
    assert result.blocker.code == "plugin_quality_root_mismatch"
    assert result.initial_capture is not None and not result.children
