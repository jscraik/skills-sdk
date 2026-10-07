"""Exercise applicable package policy from a wheel in an isolated directory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import skills_sdk
from skills_sdk.validation import SkillValidationPolicy, validate_skill_package


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
            assert (root / "SKILL.md").read_bytes() == skill
    print("installed package-quality API and CLI: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
