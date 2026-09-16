from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from skills_sdk.cli import main as main_module
from skills_sdk.cli.main import main

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "synthetic-skill"


def _write_context(path: Path, *, owner_unchanged: bool = True) -> None:
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
                "checks": {
                    "identity": True,
                    "provenance": True,
                    "rights": True,
                    "owner_unchanged": owner_unchanged,
                },
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


def test_intake_cli_non_admit_decision_exits_two_and_is_visible(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = tmp_path / "context.json"
    _write_context(context, owner_unchanged=False)
    assert main(["intake", str(FIXTURE_ROOT), "--context", str(context), "--json"]) == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "normalized"
    assert receipt["decision"]["decision"] == "needs_owner_decision"
    assert receipt["decision"]["blocker_codes"] == ["owner_decision_required"]

    assert main(["intake", str(FIXTURE_ROOT), "--context", str(context)]) == 2
    output = capsys.readouterr().out
    assert "decision: needs_owner_decision" in output
    assert "decision_blocker: owner_decision_required" in output


def test_intake_cli_rejects_invalid_context_without_echoing_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = tmp_path / "context.json"
    secret = "sk-rejected-secret-material"
    context.write_text(json.dumps({"source_repository": secret}), encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main(["intake", str(FIXTURE_ROOT), "--context", str(context), "--json"])
    captured = capsys.readouterr()
    assert "invalid intake context" in captured.err
    assert secret not in captured.err


def test_intake_cli_rejects_fifo_and_symlink_contexts_without_blocking(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fifo = tmp_path / "context.fifo"
    os.mkfifo(fifo)
    with pytest.raises(SystemExit, match="2"):
        main(["intake", str(FIXTURE_ROOT), "--context", str(fifo), "--json"])
    assert "invalid intake context" in capsys.readouterr().err

    target = tmp_path / "context.json"
    _write_context(target)
    link = tmp_path / "context-link.json"
    link.symlink_to(target)
    with pytest.raises(SystemExit, match="2"):
        main(["intake", str(FIXTURE_ROOT), "--context", str(link), "--json"])
    assert "invalid intake context" in capsys.readouterr().err


def test_intake_cli_rejects_symlinked_context_ancestor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    _write_context(target / "context.json")
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(SystemExit, match="2"):
        main(["intake", str(FIXTURE_ROOT), "--context", str(link / "context.json"), "--json"])
    assert "invalid intake context" in capsys.readouterr().err


def test_intake_cli_validates_the_context_wire_shape_before_normalization(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = tmp_path / "context.json"
    _write_context(context)
    payload = json.loads(context.read_text(encoding="utf-8"))
    payload["source_revision"] = f" {payload['source_revision']} "
    context.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        main(["intake", str(FIXTURE_ROOT), "--context", str(context), "--json"])
    assert "invalid intake context" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"])
def test_intake_cli_emits_typed_blocker_without_safe_open_support(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
) -> None:
    context = tmp_path / "context.json"
    _write_context(context)
    monkeypatch.setattr(main_module.os, flag, 0)

    assert main(["intake", str(FIXTURE_ROOT), "--context", str(context), "--json"]) == 2
    blocker = json.loads(capsys.readouterr().out)
    assert blocker["code"] == "unsupported_context_read"
    assert blocker["evidence_refs"] == ["docs/compatibility.md"]


def test_intake_cli_rejects_duplicate_context_members(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = tmp_path / "context.json"
    context.write_text('{"checks": {}, "checks": {}}', encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        main(["intake", str(FIXTURE_ROOT), "--context", str(context), "--json"])
    assert "invalid intake context" in capsys.readouterr().err


def test_intake_cli_rejects_parent_components_before_open(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    context = tmp_path / "context.json"
    _write_context(context)

    with pytest.raises(SystemExit, match="2"):
        main(["intake", str(FIXTURE_ROOT), "--context", str(directory / ".." / "context.json"), "--json"])
    assert "invalid intake context" in capsys.readouterr().err


def test_intake_cli_treats_decoder_recursion_as_invalid_context(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = tmp_path / "context.json"
    context.write_text("[" * 10_000 + "]" * 10_000, encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        main(["intake", str(FIXTURE_ROOT), "--context", str(context), "--json"])
    assert "invalid intake context" in capsys.readouterr().err
