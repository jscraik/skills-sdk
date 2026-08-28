#!/usr/bin/env python3
"""Validate portable source, documentation, and repository standards."""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MAX_MODULE_LINES = 800
MAX_FUNCTION_LINES = 120
MAX_PUBLIC_PARAMETERS = 5
PYTHON_ROOTS = ("src", "scripts", "tests")
TEXT_ROOTS = ("src", "scripts", "tests", "docs")
PORTABLE_TEXT_FILES = (
    "AGENTS.md",
    "ARCHITECTURE.md",
    "CHANGELOG.md",
    "CODESTYLE.md",
    "CONTRIBUTING.md",
    "README.md",
    "SECURITY.md",
    "UBIQUITOUS.md",
    "pyproject.toml",
    ".mise.toml",
)
REQUIRED_IGNORES = (".venv/", ".pytest_cache/", ".ruff_cache/", "__pycache__/", "dist/", "build/")
SUPPRESSION_FRAGMENTS = (
    "type:" + " ignore",
    "pyright:" + " ignore",
    "noqa",
    "pylint:" + " disable",
    "pragma:" + " no cover",
    "fmt:" + " off",
    "fmt:" + " skip",
)
MACHINE_PATH_PATTERNS = (
    re.compile("/" + r"Users/[^/\s]+/"),
    re.compile("/" + r"home/[^/\s]+/"),
    re.compile(r"[A-Za-z]:\\" + r"Users\\[^\\\s]+\\"),
)
PINNED_TOOLS = {
    "uv": "0.11.3",
    "ruff": "0.15.22",
    "pytest": "9.1.1",
    "mypy": "1.18.1",
    "types_jsonschema": "4.26.0.20260518",
    "types_pyyaml": "6.0.12.20250822",
    "uv_build": "0.11.3",
    "vale": "3.19.0",
}
MISE_ACTION = "jdx/mise-action@v4"
PR_TEMPLATE_VALIDATOR = ".github/scripts/validate_pr_template_body.py"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    code: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code}: {self.message}"


def _iter_files(root: Path, directories: Sequence[str], suffixes: tuple[str, ...]) -> Iterable[Path]:
    for directory in directories:
        base = root / directory
        if base.is_dir():
            yield from sorted(path for path in base.rglob("*") if path.is_file() and path.suffix in suffixes)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _suppression_findings(root: Path, path: Path) -> list[Finding]:
    findings: list[Finding] = []
    content = path.read_text(encoding="utf-8")
    try:
        comments = (
            token for token in tokenize.generate_tokens(io.StringIO(content).readline) if token.type == tokenize.COMMENT
        )
        for token in comments:
            normalized = token.string.casefold()
            for fragment in SUPPRESSION_FRAGMENTS:
                if fragment in normalized:
                    findings.append(
                        Finding(
                            _relative(root, path),
                            token.start[0],
                            "suppression",
                            f"forbidden comment contains {fragment!r}",
                        )
                    )
    except (IndentationError, tokenize.TokenError) as error:
        findings.append(Finding(_relative(root, path), 1, "tokenize", str(error)))
    return findings


def _annotation_missing(argument: ast.arg) -> bool:
    return argument.annotation is None and argument.arg not in {"self", "cls"}


def _public_function_findings(relative: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Finding]:
    if node.name.startswith("_"):
        return []
    findings: list[Finding] = []
    arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if any(_annotation_missing(argument) for argument in arguments) or (
        node.args.vararg and not node.args.vararg.annotation
    ):
        findings.append(Finding(relative, node.lineno, "public-typing", "public parameters require annotations"))
    if node.args.kwarg and not node.args.kwarg.annotation:
        findings.append(
            Finding(relative, node.lineno, "public-typing", "public keyword parameters require annotations")
        )
    if node.returns is None:
        findings.append(Finding(relative, node.lineno, "public-typing", "public return type is required"))
    parameter_count = len(arguments) + int(node.args.vararg is not None) + int(node.args.kwarg is not None)
    if parameter_count > MAX_PUBLIC_PARAMETERS:
        findings.append(
            Finding(
                relative,
                node.lineno,
                "public-parameters",
                f"{parameter_count} parameters exceeds {MAX_PUBLIC_PARAMETERS}",
            )
        )
    function_lines = (node.end_lineno or node.lineno) - node.lineno + 1
    if function_lines > MAX_FUNCTION_LINES:
        findings.append(
            Finding(relative, node.lineno, "function-size", f"{function_lines} lines exceeds {MAX_FUNCTION_LINES}")
        )
    return findings


def _import_targets(node: ast.Import | ast.ImportFrom, relative: str) -> tuple[str, ...]:
    if isinstance(node, ast.ImportFrom):
        if node.level == 0:
            return (node.module or "",)
        containing_package = list(Path(relative).with_suffix("").parts[1:-1])
        retained_parts = max(0, len(containing_package) - node.level + 1)
        target_parts = [*containing_package[:retained_parts], *(node.module or "").split(".")]
        return (".".join(part for part in target_parts if part),)
    return tuple(alias.name for alias in node.names)


def _forbidden_imports(relative: str) -> tuple[str, ...]:
    if relative.startswith("src/skills_sdk/core/"):
        return (
            "skills_sdk.adapters",
            "skills_sdk.cli",
            "skills_sdk.evaluation",
            "skills_sdk.host_adapters",
            "skills_sdk.packaging",
            "skills_sdk.providers",
            "skills_sdk.validation",
        )
    if relative.startswith("src/skills_sdk/models/"):
        return (
            "skills_sdk.adapters",
            "skills_sdk.cli",
            "skills_sdk.evaluation",
            "skills_sdk.host_adapters",
            "skills_sdk.packaging",
            "skills_sdk.providers",
            "skills_sdk.validation",
        )
    if relative.startswith("src/skills_sdk/validation/"):
        return ("skills_sdk.cli", "skills_sdk.evaluation", "skills_sdk.packaging")
    if relative.startswith(("src/skills_sdk/evaluation/", "src/skills_sdk/packaging/")):
        return ("skills_sdk.cli",)
    return ()


def _catches_broad_exception(node: ast.expr | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in {"Exception", "BaseException"}
    if isinstance(node, ast.Tuple):
        return any(_catches_broad_exception(item) for item in node.elts)
    return False


def _python_findings(root: Path, path: Path) -> list[Finding]:
    relative = _relative(root, path)
    content = path.read_text(encoding="utf-8")
    findings = _suppression_findings(root, path)
    line_count = len(content.splitlines())
    if line_count > MAX_MODULE_LINES:
        findings.append(Finding(relative, 1, "module-size", f"{line_count} lines exceeds {MAX_MODULE_LINES}"))
    try:
        tree = ast.parse(content, filename=relative)
    except SyntaxError as error:
        return [*findings, Finding(relative, error.lineno or 1, "syntax", error.msg)]
    forbidden = _forbidden_imports(relative)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            findings.extend(_public_function_findings(relative, node))
        elif isinstance(node, ast.Global):
            findings.append(Finding(relative, node.lineno, "global-state", "global declarations are forbidden"))
        elif isinstance(node, ast.ExceptHandler) and _catches_broad_exception(node.type):
            findings.append(Finding(relative, node.lineno, "broad-except", "catch a specific exception"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for target in _import_targets(node, relative):
                if any(target == prefix or target.startswith(f"{prefix}.") for prefix in forbidden):
                    findings.append(
                        Finding(relative, node.lineno, "dependency-direction", f"forbidden import {target!r}")
                    )
    return findings


def _portable_text_findings(root: Path) -> list[Finding]:
    paths = list(_iter_files(root, TEXT_ROOTS, (".py", ".md", ".toml", ".yaml", ".yml", ".json")))
    paths.extend(root / name for name in PORTABLE_TEXT_FILES if (root / name).is_file())
    findings: list[Finding] = []
    for path in sorted(set(paths)):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if any(pattern.search(line) for pattern in MACHINE_PATH_PATTERNS):
                findings.append(Finding(_relative(root, path), line_number, "machine-path", "machine-specific path"))
    return findings


def _local_link_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    repository_root = root.resolve()
    markdown_paths = list(_iter_files(root, ("docs",), (".md",)))
    markdown_paths.extend(
        root / name for name in PORTABLE_TEXT_FILES if name.endswith(".md") and (root / name).is_file()
    )
    link_pattern = re.compile(r"(?<!!)\[[^]]*]\(([^)]+)\)")
    for path in sorted(set(markdown_paths)):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in link_pattern.finditer(line):
                destination_tokens = match.group(1).strip().split()
                destination = destination_tokens[0].strip("<>") if destination_tokens else ""
                if not destination or destination.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                target = (path.parent / destination.split("#", 1)[0]).resolve()
                try:
                    target.relative_to(repository_root)
                except ValueError:
                    findings.append(
                        Finding(
                            _relative(root, path),
                            line_number,
                            "broken-link",
                            f"local target escapes repository root {destination!r}",
                        )
                    )
                    continue
                if not target.exists():
                    findings.append(
                        Finding(
                            _relative(root, path), line_number, "broken-link", f"missing local target {destination!r}"
                        )
                    )
    return findings


def _dependency_version(requirements: Sequence[str], package: str) -> str | None:
    prefix = f"{package}=="
    return next(
        (requirement.removeprefix(prefix) for requirement in requirements if requirement.startswith(prefix)), None
    )


def _tooling_suppression_findings(pyproject: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    tool = pyproject.get("tool", {})
    ruff = tool.get("ruff", {})
    ruff_lint = ruff.get("lint", {})
    prohibited_ruff = {key for key in ("exclude", "extend-exclude") if key in ruff} | {
        key for key in ("ignore", "extend-ignore", "per-file-ignores") if key in ruff_lint
    }
    if prohibited_ruff:
        findings.append(
            Finding(
                "pyproject.toml", 1, "tool-suppression", f"prohibited Ruff suppression keys: {sorted(prohibited_ruff)}"
            )
        )
    mypy = tool.get("mypy", {})
    prohibited_mypy = {key for key in ("disable_error_code", "exclude", "ignore_errors") if key in mypy}
    if mypy.get("follow_imports") == "skip":
        prohibited_mypy.add("follow_imports=skip")
    if tool.get("mypy", {}).get("overrides") or tool.get("mypy-overrides"):
        prohibited_mypy.add("overrides")
    if prohibited_mypy:
        findings.append(
            Finding(
                "pyproject.toml",
                1,
                "tool-suppression",
                f"prohibited MyPy suppression keys: {sorted(prohibited_mypy)}",
            )
        )
    return findings


def _tool_pin_findings(pyproject: dict[str, Any], mise: dict[str, Any], lock: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    dev_dependencies = pyproject["dependency-groups"]["dev"]
    build_requirements = pyproject["build-system"]["requires"]
    observed = {
        "uv": mise["tools"].get("uv"),
        "ruff": _dependency_version(dev_dependencies, "ruff"),
        "pytest": _dependency_version(dev_dependencies, "pytest"),
        "mypy": _dependency_version(dev_dependencies, "mypy"),
        "types_jsonschema": _dependency_version(dev_dependencies, "types-jsonschema"),
        "types_pyyaml": _dependency_version(dev_dependencies, "types-pyyaml"),
        "uv_build": _dependency_version(build_requirements, "uv_build"),
        "vale": mise["tools"].get("vale"),
    }
    if mise["tools"].get("ruff") != observed["ruff"]:
        findings.append(Finding(".mise.toml", 1, "tool-pin", "Ruff must match the exact project dependency"))
    if mise["tools"].get("python") != "3.12" or pyproject["project"]["requires-python"] != ">=3.12,<3.13":
        findings.append(
            Finding("pyproject.toml", 1, "python-version", "Python 3.12 must be exact at repository boundaries")
        )
    for tool, expected in PINNED_TOOLS.items():
        if observed[tool] != expected:
            findings.append(Finding("pyproject.toml", 1, "tool-pin", f"{tool} must be pinned to {expected}"))
    locked = {package["name"].replace("-", "_"): package["version"] for package in lock["package"]}
    for tool in ("ruff", "pytest", "mypy", "types_jsonschema", "types_pyyaml"):
        if locked.get(tool) != PINNED_TOOLS[tool]:
            findings.append(Finding("uv.lock", 1, "lock-pin", f"{tool} lock must be {PINNED_TOOLS[tool]}"))
    return findings


def _config_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    mise = tomllib.loads((root / ".mise.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    findings.extend(_tooling_suppression_findings(pyproject))
    findings.extend(_tool_pin_findings(pyproject, mise, lock))
    for path in _iter_files(root, ("src/skills_sdk/schemas", "tests/fixtures"), (".json",)):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            findings.append(Finding(_relative(root, path), error.lineno, "json", error.msg))
    pr_template_enforced = False
    for path in _iter_files(root, (".github/workflows",), (".yaml", ".yml")):
        workflow_text = path.read_text(encoding="utf-8")
        if "trusted-base/.github/scripts/validate_pr_template_body.py" in workflow_text:
            pr_template_enforced = True
        try:
            workflow = yaml.safe_load(workflow_text)
        except yaml.YAMLError as error:
            findings.append(Finding(_relative(root, path), 1, "yaml", str(error)))
            continue
        for job in workflow.get("jobs", {}).values():
            steps = job.get("steps", [])
            validate_indexes = [
                index
                for index, step in enumerate(steps)
                if "bash scripts/validate-repository.sh" in str(step.get("run", ""))
            ]
            if not validate_indexes:
                continue
            mise_indexes = [
                index
                for index, step in enumerate(steps)
                if step.get("uses") == MISE_ACTION
                and step.get("with", {}).get("install", True) is not False
                and ("install_args" not in step.get("with", {}) or "vale" in str(step["with"]["install_args"]).split())
            ]
            if not mise_indexes or min(mise_indexes) > min(validate_indexes):
                findings.append(
                    Finding(
                        _relative(root, path),
                        1,
                        "ci-tooling",
                        f"{MISE_ACTION} must install Vale before repository validation",
                    )
                )
    if (root / ".github/PULL_REQUEST_TEMPLATE.md").is_file() and not pr_template_enforced:
        findings.append(
            Finding(
                ".github/workflows",
                1,
                "pr-template",
                f"hosted validation must invoke trusted-base/{PR_TEMPLATE_VALIDATOR}",
            )
        )
    ignored = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    for required in REQUIRED_IGNORES:
        if required not in ignored:
            findings.append(Finding(".gitignore", 1, "generated-output", f"missing ignore {required!r}"))
    return findings


def check_repository(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_files(root, PYTHON_ROOTS, (".py",)):
        findings.extend(_python_findings(root, path))
    findings.extend(_portable_text_findings(root))
    findings.extend(_local_link_findings(root))
    findings.extend(_config_findings(root))
    return sorted(findings, key=lambda finding: (finding.path, finding.line, finding.code))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    findings = check_repository(args.root.resolve())
    for finding in findings:
        print(finding.render())
    if findings:
        print(f"repository standards: fail ({len(findings)} findings)", file=sys.stderr)
        return 1
    print("repository standards: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
