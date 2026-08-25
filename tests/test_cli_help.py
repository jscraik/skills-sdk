from __future__ import annotations

import pytest

from skills_sdk.cli.main import main


def test_help_exposes_boundary_only_cli(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Portable lifecycle contracts" in output
    assert "inventory" in output
    assert "tessl" in output
    assert "candidate_content_sha256" not in output


def test_optional_contract_detail_is_loaded_by_explicit_command_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["inventory", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "read-only source inventory" in output
    assert "candidate_content_sha256" not in output


def test_version_is_available(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == "skills-sdk 0.1.0"
