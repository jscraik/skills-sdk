"""Profile-bound calibration CLI rejects stale configuration and recovers."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_codex_profile_binding import _profile_plan
from test_codex_profile_invocation import _CONFIGURED
from test_matched_calibration import _dimensions
from test_matched_offline_cli import _variant
from test_matched_profile_cli_inputs import _profiles

from skills_sdk.cli.main import main
from skills_sdk.cli.matched_offline import _FixtureJudge
from skills_sdk.core.schema_registry import SchemaRegistry


def test_profile_calibration_cli_rejects_and_recovers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_plan = _profile_plan(_CONFIGURED)
    lane = profile_plan.lanes[0]
    plan, frames, _ = _dimensions(tmp_path, trials=lane.judge_parameters.trial_count, provider_identity=lane.judge)
    payload = {
        "plan": plan.model_dump(mode="json"),
        "rubric": profile_plan.rubric.model_dump(mode="json"),
        "executions": [_variant(frame, profile_plan.rubric) for frame in frames],
        "profile_plan": profile_plan.model_dump(mode="json"),
        "profiles": _profiles(profile_plan),
    }
    calls = []
    original = _FixtureJudge.judge

    async def observe(self: object, inputs: object) -> object:
        assert "expected_label" not in inputs.__dataclass_fields__
        assert "expected_label" not in str(inputs.selected.request.model_dump(mode="json"))
        calls.append(inputs)
        return await original(self, inputs)

    monkeypatch.setattr(_FixtureJudge, "judge", observe)
    source = tmp_path / "profile-calibration.json"
    command = ["eval", "matched-calibration", "--input", str(source), "--adapter-mode", "supplied-offline", "--json"]
    rejected = deepcopy(payload)
    rejected["profiles"]["judge"]["configuration_sha256"] = "0" * 64
    mismatched = deepcopy(payload)
    mismatched["executions"][0]["judge"]["parameters"]["temperature"] = 0.5
    missing_plan = deepcopy(payload)
    del missing_plan["profile_plan"]
    for data, expected in ((rejected, 2), (mismatched, 2), (missing_plan, 2), (payload, 0)):
        source.write_text(json.dumps(data))
        assert main(command) == expected
        receipt = json.loads(capsys.readouterr().out)
        SchemaRegistry().validate("matched-calibration.v1", receipt)
        if expected:
            assert not calls
        else:
            assert len(calls) == 6 * lane.judge_parameters.trial_count
            assert receipt["status"] == "pass"
            assert not receipt["external_authenticity_verified"]
