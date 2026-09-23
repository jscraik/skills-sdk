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


def test_cli_human_output_shows_case_blocker(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Render the nested case blocker in the default human-readable route."""
    package = _skill(tmp_path / "simplify")
    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    host_input = tmp_path / "missing-adapter.json"
    host_input.write_text(
        json.dumps({"request": request.model_dump(mode="json"), "input_payload": input_payload}), encoding="utf-8"
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
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "case happy-diff: blocked" in output
    assert "provider_adapter_required" in output


def test_cli_human_output_shows_failed_case_detail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Render observed forbidden commands for a failing selected case."""
    package = _skill(tmp_path / "simplify")
    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output_text = "Preserve behavior; rm -rf is forbidden."
    host_input = tmp_path / "failed-case.json"
    host_input.write_text(
        json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "input_payload": input_payload,
                "adapter": {
                    "descriptor": _adapter(request, output_text).descriptor.model_dump(mode="json"),
                    "output_text": output_text,
                    "evidence_refs": ["evidence/provider-output.json"],
                },
                "assertion_evidence": _evidence(definition, request, output_text).model_dump(mode="json"),
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
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "case happy-diff: fail" in output
    assert "forbidden_commands_observed: rm -rf" in output
