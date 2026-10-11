"""Whole-plugin matched profile CLI proof with freshly generated calibration."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_codex_profile_invocation import _CONFIGURED
from test_matched_execution import _matched
from test_matched_offline_cli import _mode_plan, _pairs
from test_matched_profile_cli_inputs import _profiles

from skills_sdk.cli.main import main
from skills_sdk.models.matched_execution import MatchedExecutionReceipt
from skills_sdk.providers.codex_profiles import describe_codex_profile


@pytest.mark.parametrize("mode", ["complete", "stream"])
def test_profile_local_cli_rejects_wrong_configuration_then_runs_ten_cases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: str
) -> None:
    identity = describe_codex_profile(_CONFIGURED, model_revision="fixture-v1")
    plan, calibrations, batch, _ = _matched(tmp_path, provider_identity=identity)
    plan = _mode_plan(plan, mode, "local")
    payload = {
        "plan": plan.model_dump(mode="json"),
        "calibrations": [item.model_dump(mode="json") for item in calibrations],
        "executions": _pairs(batch, plan.rubric, mode),
        "profiles": _profiles(plan),
    }
    invalid = deepcopy(payload)
    invalid["profiles"]["judge"]["configuration_sha256"] = "0" * 64
    path = tmp_path / "profile-execution.json"
    args = ["eval", "matched-local", "--input", str(path), "--adapter-mode", "supplied-offline", "--json"]
    for data, expected in ((invalid, 2), (payload, 0)):
        path.write_text(json.dumps(data))
        assert main(args) == expected
        receipt = MatchedExecutionReceipt.model_validate_json(capsys.readouterr().out)
        assert receipt.provider_invocation_count == receipt.judge_invocation_count == (0 if expected else 40)
        if not expected:
            assert receipt.plan == plan
            assert len(receipt.plan.case_bindings) == 10
            assert receipt.plan.lanes[0].generator.adapter_version_or_digest == identity.adapter_version_or_digest
            assert receipt.external_authenticity_verified is False
