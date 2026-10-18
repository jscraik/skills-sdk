"""Installed whole-plugin API/CLI acceptance, rejection and recovery proof."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import skills_sdk
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import check_plugin_quality


def prepare(root: Path) -> None:
    """Prepare synthetic fixtures outside the installed interpreter."""
    from test_plugin_quality import _plugin

    root.mkdir()
    _plugin_root, request, assessments, presentation = _plugin(root)
    for name, payload in (("request", request), ("assessments", assessments), ("presentation", presentation)):
        (root / (name + ".json")).write_text(json.dumps(payload), encoding="utf-8")


def check(root: Path) -> None:
    """Run public installed services without importing checkout fixtures or pytest."""
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    assert "pytest" not in sys.modules
    request = json.loads((root / "request.json").read_text())
    assessments = json.loads((root / "assessments.json").read_text())
    presentation = json.loads((root / "presentation.json").read_text())
    command = [
        str(Path(sys.executable).with_name("skills-sdk.exe" if sys.platform == "win32" else "skills-sdk")),
        "check-plugin-quality",
        str(root / "plugin"),
        "--request",
        str(root / "request.json"),
        "--assessments",
        str(root / "assessments.json"),
        "--json",
        "--robot",
    ]
    for supplied, expected in (
        (False, "blocked"),
        (True, "local_checks_passed"),
        (False, "blocked"),
        (True, "local_checks_passed"),
    ):
        api = asyncio.run(
            check_plugin_quality(
                root / "plugin",
                request,
                assessments=assessments,
                presentation_request=presentation if supplied else None,
            )
        )
        assert api.status == expected
        selected = [*command, "--presentation-request", str(root / "presentation.json")] if supplied else command
        result = subprocess.run(selected, cwd=root, capture_output=True, text=True, check=False)
        assert not result.stderr, result.stderr
        assert result.returncode == (0 if supplied else 2)
        payload = json.loads(result.stdout)
        assert payload == api.model_dump(mode="json")
        SchemaRegistry().validate("plugin-quality.v1", payload)
        assert payload["release_ready"] is payload["mutation_performed"] is False
    assert not any("agent_skills" in name or "skills_foundry" in name for name in sys.modules)
    print("installed whole-plugin quality API/CLI acceptance, rejection and recovery: pass")


if __name__ == "__main__":
    mode, directory = sys.argv[1:]
    if mode == "--prepare":
        prepare(Path(directory).resolve())
    elif mode == "--check":
        check(Path(directory).resolve())
    else:
        raise ValueError("select --prepare or --check")
