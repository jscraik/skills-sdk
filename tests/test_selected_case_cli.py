"""CLI coverage for selected-case evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_selected_case_evaluation import REVISION, _adapter, _evidence, _prepared_request, _skill

from skills_sdk.cli.main import main
from skills_sdk.evaluation import load_selected_case


def test_cli_runs_controlled_supplied_adapter_without_agent_skills(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Run the controlled selected-case CLI route without Agent-Skills."""
    package = _skill(tmp_path / "simplify")
    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "Preserve behavior with focused validation."
    host_input = tmp_path / "host-input.json"
    host_input.write_text(
        json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "input_payload": input_payload,
                "adapter": {
                    "descriptor": _adapter(request, output).descriptor.model_dump(mode="json"),
                    "output_text": output,
                    "evidence_refs": ["evidence/provider-output.json"],
                },
                "assertion_evidence": _evidence(definition, request, output).model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "eval",
            "selected-case",
            str(package),
            "--source-revision",
            REVISION,
            "--case",
            "happy-diff",
            "--mode",
            "release",
            "--host-input",
            str(host_input),
            "--json",
            "--robot",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["schema_version"] == "evaluation-receipt/v2"
    assert payload["status"] == "pass"
    assert "Agent-Skills" not in json.dumps(payload)


def test_cli_rejects_malformed_supplied_final_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Reject malformed caller-supplied output at the CLI boundary."""
    package = _skill(tmp_path / "simplify")
    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    request = _prepared_request(definition, None)
    host_input = tmp_path / "malformed.json"
    host_input.write_text(
        json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "input_payload": None,
                "adapter": {
                    "descriptor": _adapter(request, "output").descriptor.model_dump(mode="json"),
                    "output_text": {"not": "text"},
                    "evidence_refs": ["evidence/provider-output.json"],
                },
                "assertion_evidence": None,
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "eval",
            "selected-case",
            str(package),
            "--source-revision",
            REVISION,
            "--case",
            "happy-diff",
            "--mode",
            "release",
            "--host-input",
            str(host_input),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["code"] == "invalid_selected_case_input"
    assert payload["evidence_refs"] == []
