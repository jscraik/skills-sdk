from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills_sdk.cli.main import main

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "synthetic-skill"


def _write_context(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "skill-package-intake-context/v1",
                "source_repository": "jscraik/skills-sdk",
                "source_revision": "1" * 40,
                "source_path": "tests/fixtures/synthetic-skill",
                "source_kind": "git",
                "owner": {
                    "schema_version": "package-owner/v1",
                    "owner": "sdk-tests",
                    "maintainer": "sdk-tests",
                    "ownership_state": "canonical",
                    "rights": {
                        "basis": "authored",
                        "license": "Apache-2.0",
                        "evidence_ref": "tests/fixtures/synthetic-skill/SKILL.md",
                    },
                },
                "checks": {"identity": True, "provenance": True, "rights": True, "owner_unchanged": True},
            }
        ),
        encoding="utf-8",
    )


def test_intake_cli_emits_normalized_receipt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    context = tmp_path / "context.json"
    _write_context(context)
    assert main(["intake", str(FIXTURE_ROOT), "--context", str(context), "--json", "--robot"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["schema_version"] == "skill-package-intake/v1"
    assert receipt["status"] == "normalized"
    assert receipt["mutation_performed"] is False


def test_intake_cli_preserves_typed_blocker(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    context = tmp_path / "context.json"
    _write_context(context)
    assert main(["intake", str(FIXTURE_ROOT), "--context", str(context), "--max-entrypoint-lines", "1", "--json"]) == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "blocked"
    assert receipt["blocker"]["code"] == "entrypoint_line_budget_exceeded"


def test_intake_cli_rejects_invalid_context(tmp_path: Path) -> None:
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main(["intake", str(FIXTURE_ROOT), "--context", str(context), "--json"])
