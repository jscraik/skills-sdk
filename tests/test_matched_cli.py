"""Real matched CLI assessment boundaries and corrected-input recovery."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from test_matched_comparison import _judgment, _plan
from test_matched_handoff import _journey

from skills_sdk.cli.main import main
from skills_sdk.core.schema_registry import SchemaRegistry


def test_matched_assessment_cli_rejects_and_recovers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plan = _plan()
    payload = {
        "plan": plan.model_dump(mode="json"),
        "lane": "local",
        "baseline": _judgment(plan, "baseline", 2.5).model_dump(mode="json"),
        "candidate": _judgment(plan, "candidate", 4.5).model_dump(mode="json"),
    }
    source = tmp_path / "input.json"
    command = ["eval", "matched-assessment", "--input", str(source), "--json", "--robot"]
    for value, expected in ((dict(payload, extra=True), 2), (payload, 0)):
        source.write_text(json.dumps(value))
        assert main(command) == expected
        receipt = json.loads(capsys.readouterr().out)
        SchemaRegistry().validate("matched-pair-assessment.v1", receipt)
        assert receipt["status"] == ("blocked" if expected else "assessed")
        assert receipt["execution_performed"] is False
    source.write_text('{"plan":null,"plan":null}')
    assert main(command) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    source.write_text(json.dumps(payload))
    link = tmp_path / "link.json"
    link.symlink_to(source)
    assert main(["eval", "matched-assessment", "--input", str(link), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_matched_handoff_cli_missing_evidence_is_typed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "input.json"
    source.write_text('{"local":null,"cloud_plan":null}')
    assert main(["eval", "matched-handoff", "--input", str(source), "--json"]) == 2
    receipt = json.loads(capsys.readouterr().out)
    SchemaRegistry().validate("matched-cloud-handoff.v1", receipt)
    assert receipt["status"] == "blocked" and receipt["promotion_authorized"] is False


def test_matched_handoff_cli_lineage_rejection_and_recovery(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    local, plan, _, _, _ = _journey(tmp_path)
    payload = {"local": local.model_dump(mode="json"), "cloud_plan": plan.model_dump(mode="json")}
    source = tmp_path / "handoff.json"
    command = ["eval", "matched-handoff", "--input", str(source), "--json", "--robot"]
    for value, expected in ((dict(payload, local=None), 2), (payload, 0)):
        source.write_text(json.dumps(value))
        assert main(command) == expected
        receipt = json.loads(capsys.readouterr().out)
        SchemaRegistry().validate("matched-cloud-handoff.v1", receipt)
        assert receipt["status"] == ("blocked" if expected else "ready")
        assert receipt["promotion_authorized"] is False


def test_matched_cli_keeps_its_own_bounded_input_reader(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A larger workflow envelope does not remove the no-follow byte boundary."""
    module = importlib.import_module("skills_sdk.cli.matched")
    original = module._MAX_MATCHED_CONTEXT_BYTES
    plan = _plan()
    source = tmp_path / "bounded.json"
    source.write_text(
        json.dumps(
            {
                "plan": plan.model_dump(mode="json"),
                "lane": "local",
                "baseline": _judgment(plan, "baseline", 2.5).model_dump(mode="json"),
                "candidate": _judgment(plan, "candidate", 4.5).model_dump(mode="json"),
            }
        )
    )
    command = ["eval", "matched-assessment", "--input", str(source), "--json"]
    monkeypatch.setattr(module, "_MAX_MATCHED_CONTEXT_BYTES", 128)
    assert main(command) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    monkeypatch.setattr(module, "_MAX_MATCHED_CONTEXT_BYTES", original)
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "assessed"
