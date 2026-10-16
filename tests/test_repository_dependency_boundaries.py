"""Keep host adapters outside portable dependency layers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_repository_standards import _python_findings


@pytest.mark.parametrize(
    "layer", ["core", "models", "validation", "intake", "packaging", "distribution", "lifecycle", "evaluation"]
)
@pytest.mark.parametrize(
    "statement",
    [
        "import skills_sdk.host_adapters",
        "import skills_sdk.host_adapters.client",
        "from skills_sdk import host_adapters",
        "from ..host_adapters import client",
        "from .. import host_adapters",
    ],
)
def test_portable_layers_reject_host_adapter_imports(tmp_path: Path, layer: str, statement: str) -> None:
    source = tmp_path / "src" / "skills_sdk" / layer / "fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text(f"{statement}\n", encoding="utf-8")

    findings = _python_findings(tmp_path, source)

    assert [(finding.code, finding.line) for finding in findings] == [("dependency-direction", 1)]


@pytest.mark.parametrize(
    "layer", ["core", "models", "validation", "intake", "packaging", "distribution", "lifecycle", "evaluation"]
)
@pytest.mark.parametrize("target", ["skills_sdk.core.errors", "skills_sdk.host_adapters_extra"])
def test_portable_layers_allow_core_and_distinct_namespaces(tmp_path: Path, layer: str, target: str) -> None:
    source = tmp_path / "src" / "skills_sdk" / layer / "fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text(f"import {target}\n", encoding="utf-8")

    assert _python_findings(tmp_path, source) == []
