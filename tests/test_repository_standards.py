from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_repository_standards import (
    _local_link_findings,
    _python_findings,
    _tool_pin_findings,
    _tooling_suppression_findings,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_repository_standards_cli_accepts_current_tree() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_repository_standards.py"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "claim",
    [
        "This package is production-ready in every environment.",
        "This package is fully validated across all lanes.",
        "Security is guaranteed.",
        "There are no security risks.",
    ],
)
def test_vale_rejects_absolute_readiness_claim(tmp_path: Path, claim: str) -> None:
    source = tmp_path / "overclaim.md"
    source.write_text(f"# Status\n\n{claim}\n", encoding="utf-8")

    result = subprocess.run(
        [
            "mise",
            "exec",
            "--",
            "vale",
            "--config",
            str(REPOSITORY_ROOT / ".vale.ini"),
            str(source),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "SkillsSDK.ClaimsBoundary" in result.stdout


def test_vale_accepts_qualified_or_negated_readiness_claims(tmp_path: Path) -> None:
    source = tmp_path / "bounded-claim.md"
    source.write_text(
        "# Status\n\n"
        "This package is not production-ready.\n\n"
        "It is fully validated against the declared local contract.\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "mise",
            "exec",
            "--",
            "vale",
            "--config",
            str(REPOSITORY_ROOT / ".vale.ini"),
            str(source),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_suppression_comment_is_rejected_without_baseline_exceptions(tmp_path: Path) -> None:
    source = tmp_path / "tests" / "fixture.py"
    source.parent.mkdir()
    source.write_text("value: int = 'invalid'  # type:" + " ignore\n", encoding="utf-8")

    findings = _python_findings(tmp_path, source)

    assert [(finding.code, finding.line) for finding in findings] == [("suppression", 1)]


def test_public_annotation_and_dependency_findings_are_typed(tmp_path: Path) -> None:
    source = tmp_path / "src" / "skills_sdk" / "core" / "fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text("from skills_sdk.cli import main\n\ndef public(value):\n    return value\n", encoding="utf-8")

    findings = _python_findings(tmp_path, source)
    codes = {finding.code for finding in findings}

    assert codes == {"dependency-direction", "public-typing"}


@pytest.mark.parametrize(
    "target",
    ["skills_sdk.providers", "skills_sdk.adapters", "skills_sdk.host_adapters"],
)
def test_core_rejects_provider_and_host_adapter_imports(tmp_path: Path, target: str) -> None:
    source = tmp_path / "src" / "skills_sdk" / "core" / "fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text(f"import {target}\n", encoding="utf-8")

    findings = _python_findings(tmp_path, source)

    assert [(finding.code, finding.line) for finding in findings] == [("dependency-direction", 1)]


def test_function_local_forbidden_import_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "src" / "skills_sdk" / "core" / "fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text("def local() -> None:\n    import skills_sdk.providers\n", encoding="utf-8")

    findings = _python_findings(tmp_path, source)

    assert [(finding.code, finding.line) for finding in findings] == [("dependency-direction", 2)]


def test_relative_forbidden_import_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "src" / "skills_sdk" / "core" / "fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text("from ..providers import client\n", encoding="utf-8")

    findings = _python_findings(tmp_path, source)

    assert [(finding.code, finding.line) for finding in findings] == [("dependency-direction", 1)]


def test_tooling_suppression_configuration_is_rejected() -> None:
    pyproject = {
        "tool": {
            "ruff": {"lint": {"per-file-ignores": {"tests/*.py": ["S101"]}}},
            "mypy": {"disable_error_code": ["assignment"]},
        }
    }

    findings = _tooling_suppression_findings(pyproject)

    assert [finding.code for finding in findings] == ["tool-suppression", "tool-suppression"]


def test_tool_pin_drift_is_rejected() -> None:
    pyproject = {
        "build-system": {"requires": ["uv_build==0.11.3"]},
        "project": {"requires-python": ">=3.12,<3.13"},
        "dependency-groups": {
            "dev": [
                "mypy==1.18.1",
                "pytest==9.1.1",
                "ruff==0.15.21",
                "types-jsonschema==4.26.0.20260518",
                "types-pyyaml==6.0.12.20250822",
            ]
        },
    }
    mise = {"tools": {"python": "3.12", "uv": "0.11.3", "ruff": "0.15.22", "vale": "3.18.0"}}
    lock = {
        "package": [
            {"name": "mypy", "version": "1.18.1"},
            {"name": "pytest", "version": "9.1.1"},
            {"name": "ruff", "version": "0.15.21"},
            {"name": "types-jsonschema", "version": "4.26.0.20260518"},
            {"name": "types-pyyaml", "version": "6.0.12.20250822"},
        ]
    }

    findings = _tool_pin_findings(pyproject, mise, lock)

    assert any(finding.code == "tool-pin" for finding in findings)
    assert any("vale" in finding.message for finding in findings)
    assert any(finding.code == "lock-pin" for finding in findings)


def test_tuple_containing_broad_exception_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "tests" / "fixture.py"
    source.parent.mkdir()
    source.write_text(
        "try:\n    value = 1\nexcept (ValueError, Exception):\n    value = 2\n",
        encoding="utf-8",
    )

    findings = _python_findings(tmp_path, source)

    assert any(finding.code == "broad-except" for finding in findings)


def test_malformed_indentation_is_a_typed_tokenize_finding(tmp_path: Path) -> None:
    source = tmp_path / "tests" / "fixture.py"
    source.parent.mkdir()
    source.write_text("if True:\n    value = 1\n  value = 2\n", encoding="utf-8")

    findings = _python_findings(tmp_path, source)

    assert any(finding.code == "tokenize" for finding in findings)


def test_missing_local_documentation_link_is_rejected(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("[Missing](missing.md)\n", encoding="utf-8")

    findings = _local_link_findings(tmp_path)

    assert [(finding.code, finding.line) for finding in findings] == [("broken-link", 1)]


def test_whitespace_only_documentation_link_does_not_crash(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("[Empty](   )\n", encoding="utf-8")

    assert _local_link_findings(tmp_path) == []


def test_existing_documentation_link_outside_repository_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    docs = repository / "docs"
    docs.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    (docs / "index.md").write_text("[Outside](../../outside.md)\n", encoding="utf-8")

    findings = _local_link_findings(repository)

    assert [(finding.code, finding.line) for finding in findings] == [("broken-link", 1)]
