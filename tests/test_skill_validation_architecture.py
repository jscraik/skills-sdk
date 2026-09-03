from __future__ import annotations

import ast
from pathlib import Path

SDK_ROOT = Path(__file__).resolve().parents[1] / "src" / "skills_sdk"
REPOSITORY_ROOT = SDK_ROOT.parents[1]
FORBIDDEN_PREFIXES = ("ask", "tessl", "codex")


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
    assert "This is not the package import graph" in architecture
    assert "public convenience exports eagerly import" in architecture


def test_architecture_binds_external_outcomes_to_explicit_evidence_lanes() -> None:
    architecture = " ".join((REPOSITORY_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8").split())
    api = " ".join((REPOSITORY_ROOT / "docs" / "api.md").read_text(encoding="utf-8").split())

    assert "exact repository commands" in architecture
    for status in ("`pass`", "`fail`", "`blocked`"):
        assert status in architecture
    for lane in ("Provider", "Registry", "Host runtime", "Tessl", "Publication"):
        assert f"| {lane} | `blocked` |" in architecture
    assert "nearest meaningful fallback" in architecture
    assert "externally observed" in api
    assert "locally validates this evidence envelope" in api
    assert "does not prove" in api
