from __future__ import annotations

import ast
import os
import shlex
import subprocess
from pathlib import Path

SDK_ROOT = Path(__file__).resolve().parents[1] / "src" / "skills_sdk"
REPOSITORY_ROOT = SDK_ROOT.parents[1]
FORBIDDEN_PREFIXES = ("ask", "tessl", "codex")
TRUST_PREFIX = 'MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- '


def _quick_start_commands(markdown: str) -> list[str]:
    quick_start = markdown.split("## Quick start", 1)[1].split("## ", 1)[0]
    bash_block = quick_start.split("```bash", 1)[1].split("```", 1)[0]
    return [line for line in bash_block.splitlines() if line]


def _assert_checkout_trust_prefixes(markdown: str) -> None:
    commands = _quick_start_commands(markdown)
    assert commands
    assert all(command.startswith(TRUST_PREFIX) for command in commands)


def test_portable_sdk_does_not_import_transitional_or_provider_hosts() -> None:
    violations: list[str] = []
    for path in sorted(SDK_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(tree):
            names: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = (node.module,)
            for name in names:
                if name in FORBIDDEN_PREFIXES or name.startswith(tuple(f"{prefix}." for prefix in FORBIDDEN_PREFIXES)):
                    violations.append(f"{path.relative_to(SDK_ROOT)}:{getattr(node, 'lineno', 0)}:{name}")
    assert violations == []


def test_validation_service_does_not_depend_on_packaging_service() -> None:
    validation_root = SDK_ROOT / "validation"
    violations: list[str] = []
    for path in sorted(validation_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "skills_sdk.packaging":
                violations.append(f"{path.relative_to(SDK_ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "skills_sdk.packaging" or alias.name.startswith("skills_sdk.packaging."):
                        violations.append(f"{path.relative_to(SDK_ROOT)}:{node.lineno}")
    assert violations == []


def test_architecture_distinguishes_cli_invocation_from_package_imports() -> None:
    architecture = " ".join((REPOSITORY_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8").split())

    assert "CLI service-invocation path" in architecture
    assert "only `validate` and `build`" in architecture
    assert "During `main()` dispatch" in architecture
    assert "routes import their validation and packaging services lazily" in architecture
    assert "This is not the package import graph" in architecture
    assert "public convenience exports eagerly import" in architecture


def test_architecture_binds_external_outcomes_to_explicit_evidence_lanes() -> None:
    architecture_source = (REPOSITORY_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    architecture = " ".join(architecture_source.split())
    api = " ".join((REPOSITORY_ROOT / "docs" / "api.md").read_text(encoding="utf-8").split())

    assert "exact repository commands" in architecture
    expected_commands = (
        'MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen '
        "pytest tests/test_public_repository_boundary.py "
        "tests/test_repository_standards.py tests/test_skill_validation_architecture.py",
        "bash scripts/validate-codestyle.sh",
        'MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen '
        "python scripts/generate_schemas.py --check",
        "bash scripts/validate-repository.sh",
        "git diff --check",
        "git verify-commit 841ab6ebbff3ffd7bee4d1ff60ecbee0d11739eb",
    )
    for command in expected_commands:
        assert f"`{command}`" in architecture

    for lane in ("Provider", "Registry", "Host runtime", "Tessl", "Publication"):
        row = next(line for line in architecture_source.splitlines() if line.startswith(f"| {lane} |"))
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert cells[1] == "`blocked`"
        assert cells[2]
        assert cells[3]

    assert "`pass`" in architecture
    assert "`fail`" in architecture
    assert "externally observed" in api
    assert "locally validates this evidence envelope" in api
    assert "does not prove" in api


def test_pull_request_template_scopes_mise_to_the_checkout() -> None:
    template = (REPOSITORY_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    ubiquitous = (REPOSITORY_ROOT / "UBIQUITOUS.md").read_text(encoding="utf-8")
    assert "From the checkout root:" in readme
    assert "Run commands from the repository checkout root" in template
    assert "Run the checkout-scoped commands below from the repository checkout root" in ubiquitous
    assert (
        'MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen '
        "pytest tests/test_repository_standards.py -q"
    ) in template


def test_checkout_scoped_documented_commands_use_the_trusted_config_and_execute() -> None:
    cli_prefix = TRUST_PREFIX + "uv run --frozen "
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    ubiquitous = (REPOSITORY_ROOT / "UBIQUITOUS.md").read_text(encoding="utf-8")
    readme_commands = _quick_start_commands(readme)
    prompt_commands = [fragment.split("`", 1)[0] for fragment in ubiquitous.split("`" + cli_prefix)[1:]]

    _assert_checkout_trust_prefixes(readme)
    assert prompt_commands
    assert len(prompt_commands) == 3

    broken_readme = readme.replace(TRUST_PREFIX + "uv sync --frozen", "uv sync --frozen", 1)
    try:
        _assert_checkout_trust_prefixes(broken_readme)
    except AssertionError:
        pass
    else:
        raise AssertionError("Quick Start prefix regression was not detected")

    version_command = next(command for command in readme_commands if command.endswith("skills-sdk --version"))
    environment = os.environ.copy()
    environment["MISE_TRUSTED_CONFIG_PATHS"] = str(REPOSITORY_ROOT / ".mise.toml")
    completed = subprocess.run(
        shlex.split(version_command.split(" ", 1)[1]),
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip()
