from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_repository_standards import (
    _config_findings,
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


@pytest.mark.parametrize(
    "statement",
    ["from skills_sdk import cli\n", "from .. import providers\n"],
)
def test_package_level_forbidden_import_alias_is_rejected(tmp_path: Path, statement: str) -> None:
    source = tmp_path / "src" / "skills_sdk" / "core" / "fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text(statement, encoding="utf-8")

    findings = _python_findings(tmp_path, source)

    assert [(finding.code, finding.line) for finding in findings] == [("dependency-direction", 1)]


@pytest.mark.parametrize(
    "directive",
    ["# mypy: ignore-errors\n", "# mypy: disable-error-code=assignment\n"],
)
def test_mypy_file_level_suppression_is_rejected(tmp_path: Path, directive: str) -> None:
    source = tmp_path / "tests" / "fixture.py"
    source.parent.mkdir()
    source.write_text(f"{directive}value: int = 'invalid'\n", encoding="utf-8")

    findings = _python_findings(tmp_path, source)

    assert [(finding.code, finding.line) for finding in findings] == [("suppression", 1)]


def test_validation_wrappers_use_repository_pinned_mise_toolchain() -> None:
    for relative in ("scripts/validate-codestyle.sh", "scripts/validate-repository.sh"):
        script = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        assert 'MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"' in script
        assert "mise exec -- uv " in script
        assert not any(line.startswith("uv ") for line in script.splitlines())


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


def test_ci_rejects_repository_validation_without_mise_vale_bootstrap(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "validate.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n"
        "  validate:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v5\n"
        "      - run: bash scripts/validate-repository.sh\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / ".mise.toml").write_text(
        (REPOSITORY_ROOT / ".mise.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        "\n".join([".venv/", ".pytest_cache/", ".ruff_cache/", "__pycache__/", "dist/", "build/"]), encoding="utf-8"
    )

    findings = _config_findings(tmp_path)

    assert [(finding.code, finding.path) for finding in findings] == [("ci-tooling", ".github/workflows/validate.yml")]


def test_ci_rejects_unenforced_pr_template_contract(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "validate.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("jobs: {}\n", encoding="utf-8")
    template = tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md"
    template.write_text("# Pull request\n\n## Summary\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / ".mise.toml").write_text(
        (REPOSITORY_ROOT / ".mise.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        "\n".join([".venv/", ".pytest_cache/", ".ruff_cache/", "__pycache__/", "dist/", "build/"]),
        encoding="utf-8",
    )

    findings = _config_findings(tmp_path)

    assert [(finding.code, finding.path) for finding in findings] == [("pr-template", ".github/workflows")]


def test_ci_fetches_live_pr_body_for_template_validation() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")

    assert "pull-requests: read" in workflow
    assert 'gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER"' in workflow
    assert '--body-file "$body_file"' in workflow
    assert "for attempt in 1 2 3 4" in workflow
    assert "github.event.pull_request.body" not in workflow


def test_ci_rejects_trusted_base_left_in_validation_workspace(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "validate.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n"
        "  validate:\n"
        "    steps:\n"
        "      - run: |\n"
        "          body_file=$RUNNER_TEMP/pr-body.md\n"
        '          gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER" --jq .body > "$body_file"\n'
        "          python3 trusted-base/.github/scripts/validate_pr_template_body.py "
        '--body-file "$body_file"\n'
        "      - uses: jdx/mise-action@v4\n"
        "        with:\n"
        '          install_args: "uv vale"\n'
        "      - run: bash scripts/validate-repository.sh\n",
        encoding="utf-8",
    )
    (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text("# Pull request\n", encoding="utf-8")
    for relative in ("pyproject.toml", ".mise.toml", "uv.lock", ".gitignore"):
        (tmp_path / relative).write_text((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")

    findings = _config_findings(tmp_path)

    assert [(finding.code, finding.path) for finding in findings] == [
        ("ci-workspace", ".github/workflows/validate.yml")
    ]


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
