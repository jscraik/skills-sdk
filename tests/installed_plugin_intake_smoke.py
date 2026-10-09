"""Prove portable plugin intake from an isolated installed wheel."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def _cli(root: Path, expected: str, evidence: Path | None = None) -> None:
    """Run the installed plugin CLI and assert the expected status, exit code and absence of authority."""
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
            *(["--verify-evidence", str(evidence)] if evidence is not None else []),
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


def _verify(root: Path, payload: dict[str, object]) -> None:
    """Check installed evidence verification, role and digest forgery rejection, and recovery."""
    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.validation import verify_plugin_package_validation

    evidence = root.parent / "validation.json"
    good = json.dumps(payload)
    assert "SYNTHETIC-PRIVATE-SETTING" not in good
    assert verify_plugin_package_validation(root, payload, source_revision="1" * 40).status == "pass"
    evidence.write_text(good, encoding="utf-8")
    _cli(root, "pass", evidence)
    forged_role = json.loads(good)
    forged_role["skills"][0]["validation"]["files"][0]["role"] = "asset"
    try:
        SchemaRegistry().validate("plugin-package-validation.v1", forged_role)
    except ContractError:
        pass
    else:
        raise AssertionError("installed schema path accepted a forged SKILL.md role")
    forged = json.loads(good)
    forged["manifest"]["openai_settings_sha256"] = "0" * 64
    assert verify_plugin_package_validation(root, forged, source_revision="1" * 40).status == "blocked"
    evidence.write_text(json.dumps(forged), encoding="utf-8")
    _cli(root, "blocked", evidence)
    evidence.write_text(good, encoding="utf-8")
    _cli(root, "pass", evidence)


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
        metadata = {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "fixture-.plugin",
            "extensions": {"com.openai": {"private": "SYNTHETIC-PRIVATE-SETTING"}},
        }
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
        _verify(root, result.model_dump(mode="json"))
    print("installed portable plugin API and CLI: accepted/rejected/recovery pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
