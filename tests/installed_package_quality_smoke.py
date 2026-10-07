"""Exercise applicable package policy from a wheel in an isolated directory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import skills_sdk
from skills_sdk.validation import SkillValidationPolicy, validate_skill_package


def _check_routes(root: Path, cwd: Path, expected: str) -> None:
    for route in ("validate", "build"):
        command = subprocess.run(
            [
                sys.executable,
                "-m",
                "skills_sdk.cli.main",
                route,
                str(root),
                "--source-revision",
                "1" * 40,
                "--require-file",
                "references/README.md",
                "--check-reference-content",
                "--json",
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        assert command.returncode == (0 if expected == "pass" else 2), command.stderr
        assert json.loads(command.stdout)["status"] == (
            "built" if route == "build" and expected == "pass" else expected
        )


def main() -> int:
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    with TemporaryDirectory(prefix="sdk-package-quality-") as directory:
        cwd = Path(directory).resolve()
        root = cwd / "quality-fixture"
        root.mkdir()
        skill = b"---\nname: quality-fixture\ndescription: Inspect examples.\n---\n# Example\n"
        (root / "SKILL.md").write_bytes(skill)
        (root / "references").mkdir()
        reference = root / "references/README.md"
        policy = SkillValidationPolicy(required_files=("references/README.md",), check_reference_content=True)
        for content, expected in [(None, "blocked"), (b" \n", "blocked"), (b"# Routing\n", "pass")]:
            if content is not None:
                reference.write_bytes(content)
            result = validate_skill_package(root, source_revision="1" * 40, policy=policy)
            assert result.status == expected, result.model_dump(mode="json")
            _check_routes(root, cwd, expected)
            assert (root / "SKILL.md").read_bytes() == skill
        structured = root / "references/example.json"
        for content, expected in [
            (b'{"score": NaN}', "blocked"),
            (b'{"score": 0}', "pass"),
            (b"[" + b"9" * 4301 + b",]", "blocked"),
            (b"[" + b"9" * 4301 + b"]", "pass"),
            (b"-" + b"9" * 4301, "pass"),
        ]:
            structured.write_bytes(content)
            result = validate_skill_package(root, source_revision="1" * 40, policy=policy)
            assert result.status == expected, result.model_dump(mode="json")
            _check_routes(root, cwd, expected)
            assert structured.read_bytes() == content
        structured.unlink()
        yaml_reference = root / "references/example.yaml"
        for content in (b"resource: !Ref Example\n", b"---\nfirst: true\n---\nsecond: false\n"):
            yaml_reference.write_bytes(content)
            result = validate_skill_package(root, source_revision="1" * 40, policy=policy)
            assert result.status == "pass", result.model_dump(mode="json")
            _check_routes(root, cwd, "pass")
            assert yaml_reference.read_bytes() == content
        assert (root / "SKILL.md").read_bytes() == skill
    print("installed package-quality API and CLI: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
