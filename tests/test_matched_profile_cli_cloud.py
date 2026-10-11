"""Profiled cloud refinement retains the accepted local candidate baseline."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_codex_profile_input import _CLOUD
from test_codex_profile_invocation import _CONFIGURED
from test_matched_execution import _matched
from test_matched_offline_cli import _pairs
from test_matched_profile_cli_inputs import _profiles

from skills_sdk.cli.main import main
from skills_sdk.cli.matched_profiles import _profile_batch
from skills_sdk.evaluation import execute_matched_lane, prepare_matched_cloud_handoff
from skills_sdk.models.matched_handoff import MatchedCloudExecutionReceipt
from skills_sdk.providers.codex_profiles import CodexProfileSource, describe_codex_profile


def test_profile_cloud_cli_rejects_drift_then_retains_local_winner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_root, cloud_root = tmp_path / "local", tmp_path / "cloud"
    local_root.mkdir()
    cloud_root.mkdir()
    identity = describe_codex_profile(_CONFIGURED, model_revision="fixture-v1")
    local_plan, calibration, batch, _ = _matched(local_root, provider_identity=identity)
    fixtures = _pairs(batch, local_plan.rubric)
    from skills_sdk.cli.matched_offline import _batch

    local = asyncio.run(
        execute_matched_lane(
            local_plan, "local", calibration, _profile_batch(_batch(fixtures), local_plan, _profiles(local_plan))
        )
    )
    assert local.status == "completed"
    defaults = b"""approval_policy = "never"
approvals_reviewer = "user"
default_permissions = "read-only"
model_reasoning_summary = "none"
model_reasoning_effort = "low"
web_search = "disabled"
hide_agent_reasoning = true
"""
    source = CodexProfileSource("oss-cloud.config.toml", _CLOUD, defaults_bytes=defaults)
    cloud_identity = describe_codex_profile(source, model_revision="fixture-v1")
    plan, calibration, batch, _ = _matched(cloud_root, variants=(4.5, 5.0, "cloud"), provider_identity=cloud_identity)
    handoff = prepare_matched_cloud_handoff(local, plan)
    assert handoff.status == "ready" and handoff.cloud_plan.baseline == local.plan.candidate
    payload = {
        "handoff": handoff.model_dump(mode="json"),
        "calibrations": [item.model_dump(mode="json") for item in calibration],
        "executions": _pairs(batch, plan.rubric),
        "profiles": _profiles(plan, source),
    }
    invalid = deepcopy(payload)
    invalid["profiles"]["generator"]["profile_toml"] += "\n"
    path = tmp_path / "profile-cloud.json"
    args = ["eval", "matched-cloud", "--input", str(path), "--adapter-mode", "supplied-offline", "--json"]
    for data, expected in ((invalid, 2), (payload, 0)):
        path.write_text(json.dumps(data))
        assert main(args) == expected
        receipt = MatchedCloudExecutionReceipt.model_validate_json(capsys.readouterr().out)
        assert receipt.execution.provider_invocation_count == (0 if expected else 40)
        if not expected:
            assert receipt.execution.plan.baseline == local.plan.candidate
            assert receipt.execution.lane == "cloud"
            assert len(receipt.execution.plan.case_bindings) == 10
            assert receipt.execution.plan.lanes[1].generator == cloud_identity
