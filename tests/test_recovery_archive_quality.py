"""Truthful local recovery provenance through maintained quality callers."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_saved_release_quality import saved_request

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import check_plugin_quality
from skills_sdk.intake import intake_skill_package
from skills_sdk.models.intake import SkillPackageIntakeContextV2, SkillPackageIntakeContextV3
from skills_sdk.models.package import ArchiveSourceSnapshot, SavedReleaseSnapshot
from skills_sdk.models.plugin_quality import PluginQualityRequestV2, PluginQualityRequestV3, PluginQualityResultV3


def archive_request(root: Path) -> tuple[Path, dict, dict, dict]:
    """Use synthetic admissions only for plumbing tests, never the actual release."""
    plugin, request, assessments, presentation = saved_request(root)
    snapshot = {
        key: value
        for key, value in request["source_snapshot"].items()
        if key not in {"locator", "source_id", "release_id", "schema_version", "binding_sha256"}
    }
    snapshot.update(
        schema_version="archive-source-snapshot/v1", acquisition="user-supplied-recovery", upstream_release=None
    )
    snapshot["binding_sha256"] = canonical_json_sha256(snapshot)
    request.update(schema_version="plugin-quality-request/v3", source_snapshot=snapshot)
    for child in request["children"]:
        child["request"]["schema_version"] = "local-check-request/v4"
        intake = child["request"]["intake"]
        intake["schema_version"] = "skill-package-intake-context/v3"
        intake["source"]["schema_version"] = "archive-source-provenance/v1"
        intake["source"]["snapshot"] = deepcopy(snapshot)
    return plugin, request, assessments, presentation


def test_archive_handoff_runs_existing_quality_and_preserves_unknown_origin(tmp_path: Path) -> None:
    """All synthetic quality neighbours can pass without invented remote IDs."""
    plugin, request, assessments, presentation = archive_request(tmp_path)
    selected = PluginQualityRequestV3.model_validate(request)
    result = asyncio.run(
        check_plugin_quality(plugin, selected, assessments=assessments, presentation_request=presentation)
    )
    assert result.status == "local_checks_passed", result.model_dump_json()
    assert result.schema_version == "plugin-quality/v3"
    assert result.children[0].schema_version == "local-check/v4"
    intake = result.children[0].stages[0].receipt
    assert intake.schema_version == "skill-package-intake/v3"
    assert intake.source.source_kind == "archive"
    assert intake.source.provenance.snapshot.upstream_release is None
    assert intake.normalized_package.schema_version == "normalized-package/v3"
    assert result.release_ready is result.execution_authorized is result.evaluation_executed is False
    assert result.mutation_performed is False
    assert PluginQualityResultV3.model_validate(result.model_dump(mode="json")) == result
    for name, payload in (
        ("plugin-quality.v3", result.model_dump(mode="json")),
        ("plugin-quality-request.v3", selected.model_dump(mode="json")),
        ("skill-package-intake.v3", intake.model_dump(mode="json")),
    ):
        registry = SchemaRegistry()
        registry.validate(name, payload)
        assert Draft202012Validator(registry.load(name)).is_valid(payload)


@pytest.mark.parametrize("check", ["provenance", "rights", "owner_unchanged", "identity"])
def test_archive_owner_assertions_do_not_promote_missing_checks(tmp_path: Path, check: str) -> None:
    """The actual caller stops at intake before any later quality callbacks."""
    plugin, request, _, _ = archive_request(tmp_path)
    request["children"][0]["request"]["intake"]["checks"][check] = False
    result = asyncio.run(check_plugin_quality(plugin, request))
    assert result.status == "blocked"
    child = result.children[0]
    assert child.blocked_stage == "intake" and len(child.stages) == 1
    assert child.stages[0].receipt.decision.checks.model_dump()[check] is False
    assert result.presentation is None and result.final_capture is None
    assert result.execution_authorized is result.release_ready is False


@pytest.mark.parametrize(
    "defect",
    [
        "archive",
        "root",
        "mode",
        "version",
        "child",
        "path",
        "acquisition",
        "invented-release",
        "missing-digest",
        "missing-binding",
        "padded-version",
    ],
)
def test_archive_substitution_or_malformed_binding_stops_before_children(tmp_path: Path, defect: str) -> None:
    """Plausible wrong bindings and unsupported origin claims fail closed."""
    plugin, request, _, _ = archive_request(tmp_path)
    snapshot = request["source_snapshot"]
    source = request["children"][0]["request"]["intake"]["source"]
    if defect == "archive":
        source["snapshot"]["archive_sha256"] = "b" * 64
        source["snapshot"]["binding_sha256"] = canonical_json_sha256(
            {k: v for k, v in source["snapshot"].items() if k != "binding_sha256"}
        )
    elif defect == "root":
        source["snapshot"]["root_candidate"]["content_sha256"] = "b" * 64
    elif defect == "mode":
        snapshot["root_mode_manifest_sha256"] = "b" * 64
    elif defect == "version":
        snapshot["version"] = "2.0.0"
        snapshot["binding_sha256"] = canonical_json_sha256({k: v for k, v in snapshot.items() if k != "binding_sha256"})
        source["snapshot"] = deepcopy(snapshot)
    elif defect == "child":
        source["candidate"]["content_sha256"] = "b" * 64
    elif defect == "path":
        source["path"] = "skills/other"
    elif defect == "acquisition":
        snapshot["acquisition"] = "authenticated-registry"
    elif defect == "invented-release":
        snapshot["upstream_release"] = "invented"
    elif defect == "missing-digest":
        del snapshot["archive_sha256"]
    elif defect == "missing-binding":
        del snapshot["binding_sha256"]
    else:
        snapshot["version"] = " 1.0.0 "
    result = asyncio.run(check_plugin_quality(plugin, request))
    assert result.status == "blocked"
    assert result.children == ()
    assert result.blocker.code in {"plugin_quality_request_invalid", "plugin_quality_root_mismatch"}
    assert result.execution_authorized is result.release_ready is False


def test_archive_source_recapture_rejects_drift_and_restoration_recovers(tmp_path: Path) -> None:
    """Receipt-bound source bytes cannot be changed without reopening identity."""
    plugin, request, _, _ = archive_request(tmp_path)
    child = request["children"][0]
    context = SkillPackageIntakeContextV3.model_validate(child["request"]["intake"])
    target = plugin / child["path"] / "SKILL.md"
    original = target.read_bytes()
    target.write_bytes(original + b"\nchanged\n")
    result = intake_skill_package(target.parent, context)
    assert result.status == "blocked" and result.blocker.code == "saved_source_candidate_mismatch"
    assert result.schema_version == "skill-package-intake/v3"
    (finding,) = result.validation.findings
    assert finding.code == result.blocker.code
    assert finding.message == result.blocker.message
    assert "archive" in finding.message.lower() and "saved-release" not in finding.message.lower()
    assert "saved_source_candidate_mismatch" in result.decision.blocker_codes
    assert result.source is None and result.normalized_package is None
    SchemaRegistry().validate("skill-package-intake.v3", result.model_dump(mode="json"))
    target.write_bytes(original)
    restored = intake_skill_package(target.parent, context)
    assert restored.status == "normalized"
    assert restored.candidate == context.source.candidate
    assert restored.blocker is None and restored.validation.status == "pass"
    assert not any("provenance" in item.message.lower() for item in restored.validation.findings)


def test_old_source_contracts_reject_archive_shapes(tmp_path: Path) -> None:
    """New explicit families cannot silently broaden old saved-release shapes."""
    _, request, _, _ = archive_request(tmp_path)
    for model, payload in (
        (SavedReleaseSnapshot, request["source_snapshot"]),
        (PluginQualityRequestV2, request),
        (SkillPackageIntakeContextV2, request["children"][0]["request"]["intake"]),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)
    snapshot = ArchiveSourceSnapshot.model_validate(request["source_snapshot"])
    assert "locator" not in snapshot.model_dump() and "release_id" not in snapshot.model_dump()
