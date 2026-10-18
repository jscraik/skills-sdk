from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

SDK_ROOT = Path(__file__).resolve().parents[1] / "src" / "skills_sdk"
REPOSITORY_ROOT = SDK_ROOT.parents[1]
FORBIDDEN_PREFIXES = ("ask", "tessl", "codex")
TRUST_PREFIX = 'MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- '


def _quick_start_commands(markdown: str) -> list[str]:
    """Return non-empty commands from every Quick Start Bash block."""
    quick_start = markdown.split("## Quick start", 1)[1].split("## ", 1)[0]
    commands: list[str] = []
    for fenced_section in quick_start.split("```bash")[1:]:
        bash_block = fenced_section.split("```", 1)[0]
        commands.extend(line for line in bash_block.splitlines() if line)
    return commands


def _assert_checkout_trust_prefixes(markdown: str) -> None:
    """Assert that every quick-start command uses the checkout trust prefix."""
    commands = _quick_start_commands(markdown)
    assert commands
    assert all(command.startswith(TRUST_PREFIX) for command in commands)


def test_portable_sdk_does_not_import_transitional_or_provider_hosts() -> None:
    """Keep portable SDK modules independent of transitional provider hosts."""
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
    """Keep the validation service independent of the packaging service."""
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


def test_reserved_cli_routes_do_not_load_host_mutation_adapter() -> None:
    """Verify discovery-only CLI routes fail closed without importing host mutation."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                [
                    "import sys",
                    "from skills_sdk.cli.main import main",
                    "from skills_sdk.cli.routes import DISCOVERY_ONLY_EXIT",
                    "for route in ('inventory', 'package', 'project'):",
                    "    assert main([route]) == DISCOVERY_ONLY_EXIT",
                    "assert 'skills_sdk.host.entrypoint' not in sys.modules",
                ]
            ),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_pull_request_template_scopes_mise_to_the_checkout() -> None:
    """Require pull-request guidance to scope mise to the checkout."""
    template = (REPOSITORY_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    cli = (REPOSITORY_ROOT / "docs/cli.md").read_text(encoding="utf-8")
    assert "From the checkout root:" in readme
    assert "Run commands from the repository checkout root" in template
    assert "Run the checkout-scoped commands below from the repository checkout root" in cli
    assert (
        'MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen '
        "pytest tests/test_repository_standards.py -q"
    ) in template


def test_checkout_scoped_documented_commands_use_the_trusted_config_and_execute() -> None:
    """Require documented commands to trust the checkout and execute."""
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    cli = (REPOSITORY_ROOT / "docs/cli.md").read_text(encoding="utf-8")
    readme_commands = _quick_start_commands(readme)
    translations = cli.split("## Prompt translations", 1)[1]
    prompt_commands = [command for command in translations.split("`")[1::2] if "mise exec" in command]

    _assert_checkout_trust_prefixes(readme)
    assert prompt_commands
    assert len(prompt_commands) == 4
    assert all(command.startswith(TRUST_PREFIX) for command in prompt_commands)

    broken_readme = readme.replace(TRUST_PREFIX + "uv sync --frozen", "uv sync --frozen", 1)
    try:
        _assert_checkout_trust_prefixes(broken_readme)
    except AssertionError:
        pass
    else:
        raise AssertionError("Quick Start prefix regression was not detected")

    broken_second_block = readme.replace(
        TRUST_PREFIX + "uv run --frozen skills-sdk inventory --help",
        "uv run --frozen skills-sdk inventory --help",
        1,
    )
    try:
        _assert_checkout_trust_prefixes(broken_second_block)
    except AssertionError:
        pass
    else:
        raise AssertionError("Second Quick Start block prefix regression was not detected")

    version_command = next(command for command in readme_commands if command.endswith("skills-sdk --version"))
    completed = subprocess.run(
        ["bash", "-c", version_command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip()


def test_documented_mise_commands_stop_parent_config_discovery() -> None:
    """Keep every checkout-scoped command isolated from parent mise config."""
    for relative in (
        ".github/PULL_REQUEST_TEMPLATE.md",
        "AGENTS.md",
        "ARCHITECTURE.md",
        "CODESTYLE.md",
        "CONTRIBUTING.md",
        "README.md",
        "SUPPORT.md",
        "GLOSSARY.md",
        "docs/agent-entrypoint.md",
        "docs/api.md",
        "docs/cli.md",
        "docs/standards.md",
    ):
        for line in (REPOSITORY_ROOT / relative).read_text(encoding="utf-8").splitlines():
            if "MISE_TRUSTED_CONFIG_PATHS=" in line:
                assert 'MISE_CEILING_PATHS="$PWD/.."' in line


def test_documented_cli_placeholders_are_shell_safe() -> None:
    placeholder = re.compile(r"(?<![\"'])<[a-z0-9-]+>(?![\"'])")
    for relative in ("README.md", "GLOSSARY.md", "docs/cli.md", "docs/scenario-quality.md"):
        for line in (REPOSITORY_ROOT / relative).read_text(encoding="utf-8").splitlines():
            if "skills-sdk" in line or "--source-revision" in line:
                assert placeholder.search(line) is None, f"{relative}: unquoted shell placeholder: {line}"


def _published_bash_function(name: str) -> str:
    document = (REPOSITORY_ROOT / "docs/cli.md").read_text(encoding="utf-8")
    start = document.index(name + "() {")
    return document[start : document.index("\n}", start) + 2]


def _proof_shell(tmp_path: Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_documented_check_propagates_result_rejection(tmp_path: Path) -> None:
    helper = _published_bash_function("check")
    for show_status in (1, 0):
        script = (
            'SNAP="$PWD"; OUT="$PWD"\n'
            "measure() { echo stable; }\nrun() { return 0; }\n"
            + f"show() {{ return {show_status}; }}\n"
            + helper
            + "\ncheck probe 0 evidence\n"
        )
        result = _proof_shell(tmp_path, script)
        assert result.returncode == show_status, result.stdout + result.stderr


def test_documented_inventory_rejects_failed_sort_and_detects_mutation(tmp_path: Path) -> None:
    (tmp_path / "package").mkdir()
    source = tmp_path / "package/source.txt"
    source.write_text("before", encoding="utf-8")
    setup = 'WORK="$PWD"; PKG="$PWD/package"\n' + _published_bash_function("inventory")
    rejected = _proof_shell(tmp_path, setup + "\nsort() { return 19; }\ninventory\n")
    assert rejected.returncode != 0, rejected.stdout + rejected.stderr
    valid = _proof_shell(
        tmp_path,
        setup
        + """
before="$(inventory)" || exit 1
printf changed > "$PKG/source.txt"
after="$(inventory)" || exit 1
[ "$before" != "$after" ] && echo MUTATION_DETECTED
""",
    )
    assert valid.returncode == 0, valid.stderr
    assert "MUTATION_DETECTED" in valid.stdout


def test_documented_renewal_requires_expected_blocker(tmp_path: Path) -> None:
    document = (REPOSITORY_ROOT / "docs/cli.md").read_text(encoding="utf-8")
    guard = re.search(r'^if assess stale-v1.*\n\[ "\$STALE_STATUS".*$', document, re.MULTILINE)
    assert guard is not None, "renewal call boundary missing"
    for errexit in ("", "set -e\n"):
        for status in (0, 1, 2):
            result = _proof_shell(
                tmp_path,
                errexit + f"assess() {{ return {status}; }}\n" + guard.group() + "\necho RECOVERY_REACHED\n",
            )
            assert result.returncode == (0 if status == 2 else 1), result.stderr
            assert ("RECOVERY_REACHED" in result.stdout) == (status == 2)
