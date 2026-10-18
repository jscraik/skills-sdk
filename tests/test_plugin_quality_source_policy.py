"""Keep final source-drift evidence under the capture policy used by the service."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from test_plugin_quality import REVISION, _passed

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.plugin_quality import PluginQualityResult
from skills_sdk.validation.plugin_package import validate_plugin_package


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
