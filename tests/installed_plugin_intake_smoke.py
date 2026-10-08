"""Prove portable plugin intake from an isolated installed wheel."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def _cli(root: Path, expected: str) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "skills_sdk.cli.main",
            "validate-plugin",
            str(root),
            "--source-revision",
            "1" * 40,
            "--json",
            "--robot",
        ],
        cwd=root.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == (0 if expected == "pass" else 2), completed.stderr + completed.stdout
    value = json.loads(completed.stdout)
    assert value["status"] == expected
    assert not value["execution_authorized"] and not value["release_ready"] and not value["mutation_performed"]


def main() -> int:
    """Exercise complete-source acceptance, rejection and recovery without siblings."""
    import skills_sdk
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.validation import validate_plugin_package

    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    with TemporaryDirectory(prefix="sdk-portable-plugin-") as directory:
        root = Path(directory).resolve() / "different-checkout-name"
        child = root / "skills" / "fixture-skill"
        child.mkdir(parents=True)
        skill = b"---\nname: fixture-skill\ndescription: Inspect synthetic examples.\n---\n"
        (child / "SKILL.md").write_bytes(skill)
        (root / "assets").mkdir()
        (root / "assets" / "icon.txt").write_text("Synthetic icon", encoding="utf-8")
        metadata = {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": "fixture-.plugin"}
        manifest = root / "plugin.json"
        for content, expected in ((json.dumps(metadata), "pass"), ("{}", "blocked"), (json.dumps(metadata), "pass")):
            manifest.write_text(content, encoding="utf-8")
            result = validate_plugin_package(root, source_revision="1" * 40)
            assert result.status == expected, result.model_dump(mode="json")
            if expected == "pass":
                assert result.candidate is not None
                assert result.candidate.package_id == "plugin-" + hashlib.sha256(b"fixture-.plugin").hexdigest()
                assert "assets/icon.txt" in {item.path for item in result.files}
                assert result.skills[0].validation.status == "pass"
                SchemaRegistry().validate("plugin-package-validation.v1", result.model_dump(mode="json"))
            _cli(root, expected)
            assert (child / "SKILL.md").read_bytes() == skill
    print("installed portable plugin API and CLI: accepted/rejected/recovery pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
