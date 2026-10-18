"""Keep final source-drift evidence under the capture policy used by the service."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_plugin_quality import REVISION, _passed, _plugin

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.plugin_quality import PluginQualityResult
from skills_sdk.validation.plugin_package import validate_plugin_package


def test_identity_drift_returns_an_unbound_blocker_and_restoration_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real renamed root cannot leak a foreign capture or raise instead of blocking."""
    from skills_sdk.evaluation import plugin_quality as service

    root, request, assessments, presentation = _plugin(tmp_path)
    manifest_path = root / "plugin.json"
    original = manifest_path.read_text()
    capture = service.validate_plugin_package
    calls = 0

    def observe(path: Path, *, source_revision: str, policy: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            manifest = json.loads(original)
            manifest["name"] = "renamed-plugin"
            manifest_path.write_text(json.dumps(manifest))
        return capture(path, source_revision=source_revision, policy=policy)

    monkeypatch.setattr(service, "validate_plugin_package", observe)
    result = asyncio.run(
        service.check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert calls == 2 and result.blocker.code == "plugin_quality_source_changed"
    assert result.final_capture.status == "blocked" and result.final_capture.candidate is None
    assert result.final_capture.policy == result.initial_capture.policy
    assert result.children and result.presentation.status == "pass"
    SchemaRegistry().validate("plugin-quality.v1", result.model_dump(mode="json"))
    assert result.release_ready is result.execution_authorized is result.mutation_performed is False
    manifest_path.write_text(original)
    monkeypatch.setattr(service, "validate_plugin_package", capture)
    recovered = asyncio.run(
        service.check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert recovered.status == "local_checks_passed"


@pytest.mark.parametrize("field", ["require_version", "require_description"])
@pytest.mark.parametrize("source_changed", [False, True])
def test_source_drift_cannot_change_capture_policy(tmp_path: Path, field: str, source_changed: bool) -> None:
    """Reject policy-only and mixed policy drift; genuine same-policy source changes recover."""
    root, _request, passed = _passed(tmp_path)
    initial = passed.initial_capture
    assert initial is not None
    if source_changed:
        (root / "assets" / "late.txt").write_text("changed source")
    final = validate_plugin_package(root, source_revision=REVISION, policy=initial.policy)
    blocker = {"code": "plugin_quality_source_changed", "message": "changed"}
    raw = {**passed.model_dump(mode="json"), "status": "blocked", "blocker": blocker}
    if source_changed:
        legitimate = {**raw, "final_capture": final.model_dump(mode="json")}
        assert PluginQualityResult.model_validate(legitimate).blocker is not None
        SchemaRegistry().validate("plugin-quality.v1", legitimate)
    altered = final.model_copy(update={"policy": final.policy.model_copy(update={field: False})})
    forged = {**raw, "final_capture": altered.model_dump(mode="json")}
    typed = passed.model_copy(update={"status": "blocked", "blocker": blocker, "final_capture": altered})
    for value in (forged, typed):
        with pytest.raises(ValidationError):
            PluginQualityResult.model_validate(value)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", forged)


@pytest.mark.parametrize("field", ["sha256", "code"])
def test_bare_digest_and_blocker_code_padding_is_rejected(tmp_path: Path, field: str) -> None:
    """Keep raw and copied result validation aligned with packaged schema rejection."""
    _root, _request, passed = _passed(tmp_path)
    raw = passed.model_dump(mode="json")
    if field == "sha256":
        target = next(
            stage["receipt"]["assessment"]["evidence"][0]
            for stage in raw["children"][0]["stages"]
            if stage["name"] == "content-review"
        )
    else:
        raw.update(status="blocked", presentation=None, final_capture=None)
        raw["blocker"] = {"code": "plugin_quality_presentation_missing", "message": "Missing supplied evidence."}
        target = raw["blocker"]
    valid = PluginQualityResult.model_validate(raw)
    SchemaRegistry().validate("plugin-quality.v1", raw)
    target[field] += " "
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", raw)
    for supplied in (raw, valid.model_copy(update=raw)):
        with pytest.raises(ValidationError):
            PluginQualityResult.model_validate(supplied)
