from __future__ import annotations

import pytest

import skills_sdk.packaging
import skills_sdk.validation
from skills_sdk.cli.main import main


@pytest.mark.parametrize("arguments", [["--help"], ["--version"], ["validate", "--help"], ["build", "--help"]])
def test_discovery_does_not_invoke_package_services(monkeypatch: pytest.MonkeyPatch, arguments: list[str]) -> None:
    """Keep help and version discovery independent of package services."""

    def unexpected_service_call(*args: object, **kwargs: object) -> None:
        """Fail discovery immediately if it invokes a package service."""
        pytest.fail("CLI discovery invoked a package service")

    monkeypatch.setattr(skills_sdk.validation, "validate_skill_package", unexpected_service_call)
    monkeypatch.setattr(skills_sdk.packaging, "build_skill_package", unexpected_service_call)

    with pytest.raises(SystemExit) as exc_info:
        main(arguments)

    assert exc_info.value.code == 0


def test_help_exposes_boundary_only_cli(capsys: pytest.CaptureFixture[str]) -> None:
    """Expose command boundaries without optional contract field details."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Portable lifecycle contracts" in output
    assert "inventory" in output
    assert "tessl" in output
    assert "candidate_content_sha256" not in output


def test_optional_contract_detail_is_loaded_by_explicit_command_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Load command-specific help only when the caller requests it."""
    with pytest.raises(SystemExit) as exc_info:
        main(["inventory", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "read-only source inventory" in output
    assert "candidate_content_sha256" not in output


def test_version_is_available(capsys: pytest.CaptureFixture[str]) -> None:
    """Report the SDK version without requiring a package input."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == "skills-sdk 0.1.0"
