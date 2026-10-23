"""Inspect executable CircleCI job commands and unconditional scheduling."""

import shlex
from typing import Any


def validation_commands(config: Any) -> list[str]:
    """Read active shell commands from the canonical validation job."""
    steps = config.get("jobs", {}).get("validate", {}).get("steps", []) if isinstance(config, dict) else []
    return [
        step["run"].get("command", "")
        for step in steps
        if isinstance(step, dict)
        and isinstance(step.get("run"), dict)
        and step["run"].get("when", "on_success") in ("on_success", "always")
    ]


def _unbranched_lines(command: str, expected: str) -> list[str]:
    """Accept unbranched shell lines and only the exact SDK phase guards."""
    lines = [line.strip() for line in command.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    phase = expected.removeprefix("bash scripts/validate-repository.sh ")
    if phase in {"docs-tests", "tests", "build", "installed"} and len(lines) == 3:
        operator = "==" if phase == "docs-tests" else "!="
        if lines[0] == f'if [[ "$SDK_CI_SCOPE" {operator} docs ]]; then' and lines[-1] == "fi":
            lines = lines[1:2]
    controls = {"if", "then", "elif", "else", "fi", "for", "while", "until", "case", "esac", "select", "function"}
    for line in lines:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|(){}<>")
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            return []
        if tokens and (
            tokens[0] in controls
            or any(token in {";", "&&", "||", "&", "(", ")", "()", "{", "}", "<", "<<", "<<<"} for token in tokens)
            or line.endswith("\\")
        ):
            return []
    return lines


def _invokes(command: str, expected: str) -> bool:
    """Match complete canonical invocations rather than echoed command fragments."""
    target = shlex.split(expected)
    environment = ["env", "-u", "GH_TOKEN", "-u", "GITHUB_TOKEN", "-u", "GITHUB_PERSONAL_ACCESS_TOKEN"]
    prefixes: tuple[list[str], ...] = ([], ["mise", "exec", "--"], environment, [*environment, "mise", "exec", "--"])
    for line in _unbranched_lines(command, expected):
        if " | " in expected:
            if line.strip() == expected:
                return True
            continue
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue
        if any(tokens == prefix + target for prefix in prefixes):
            return True
    return False


def command_contract_findings(config: Any) -> list[tuple[str, str]]:
    """Retain ordered executable preparation, tooling and validation phases."""
    commands = validation_commands(config)
    findings: list[tuple[str, str]] = []
    ordered = (
        "bash scripts/circleci_pr_contract.sh",
        "mise install python uv ruff vale",
        "bash scripts/validate-repository.sh quality",
    )
    positions = [
        next((i for i, command in enumerate(commands) if _invokes(command, step)), len(commands)) for step in ordered
    ]
    if positions != sorted(set(positions)) or positions[-1] == len(commands):
        findings.append(("ci-contract", "trusted PR preparation must run before validation"))
    archive = "/".join(("", "tmp", "mise.tar.gz"))
    tooling = (
        "mise install python uv ruff vale",
        f'echo "64d5f34aeb7a4e0e327dc1c9be66cd8162e14899a47b11901154a100285a3d61  {archive}" | sha256sum -c -',
        "uv sync --frozen",
    )
    for step in tooling:
        if not any(_invokes(command, step) for command in commands):
            findings.append(("ci-tooling", "missing executable pinned tooling"))
    for phase in ("quality", "docs-tests", "tests", "build", "installed", "diff"):
        if not any(_invokes(command, f"bash scripts/validate-repository.sh {phase}") for command in commands):
            findings.append(("ci-validation", f"missing validation phase: {phase}"))
    return findings


def validation_scheduled(config: Any) -> bool:
    """Require a validate invocation without branch, event or dependency gates."""
    workflows = config.get("workflows", {}) if isinstance(config, dict) else {}
    if not isinstance(workflows, dict):
        return False
    return any(
        entry == "validate"
        or (
            isinstance(entry, dict)
            and isinstance(entry.get("validate"), dict)
            and not any(key in entry["validate"] for key in ("filters", "requires", "type", "matrix"))
        )
        for definition in workflows.values()
        if isinstance(definition, dict)
        and not any(key in definition for key in ("when", "unless", "triggers"))
        and isinstance(definition.get("jobs"), list)
        for entry in definition["jobs"]
    )
