"""Audit the installed wheel without importing a sibling project or pytest."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

import skills_sdk
from skills_sdk.evaluation import assess_scenario_coverage
from skills_sdk.validation import validate_skill_package


def main() -> int:
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    with TemporaryDirectory(prefix="sdk-coverage-") as directory:
        cwd = Path(directory).resolve()
        root = cwd / "coverage-fixture"
        root.mkdir()
        skill = b"---\nname: coverage-fixture\ndescription: Audit fixtures.\n---\n"
        (root / "SKILL.md").write_bytes(skill)
        (root / "references").mkdir()
        cases = [
            {
                "id": f"case-{index}",
                "category": "regression" if index == 0 else "edge" if index == 1 else "happy",
                "unit": "coverage",
                "given": "A supplied candidate has claims.",
                "should": "Retain all cases and gaps.",
                "realistic": True,
                "why_realistic": "Maintainers audit coverage before execution.",
                "prompt": "Audit the fixture.",
                "reproduce": "skills-sdk eval scenario-coverage",
                "eval_modes": ["release"],
                "deterministic_checks": {"forbidden_commands": ["rm -rf"]},
                "acceptance": [{"type": "expected_signal", "value": "coverage"}],
            }
            for index in range(10)
        ]
        payload = {
            "schema_version": "2.0",
            "skill_name": root.name,
            "cases": cases,
            "release_scenario_sets": [
                {
                    "id": "active",
                    "minimum_scenarios": 10,
                    "target_scenarios": 10,
                    "maximum_scenarios": 10,
                    "cases": [case["id"] for case in cases],
                }
            ],
        }
        (root / "references/evals.yaml").write_text(yaml.safe_dump(payload))
        candidate = validate_skill_package(root, source_revision="1" * 40).candidate
        assert candidate is not None
        plan = {
            "schema_version": "scenario-coverage-plan/v1",
            "candidate": candidate.model_dump(mode="json"),
            "scenario_set_id": "active",
            "claims": [{"id": "preserve", "statement": "Preserve candidate bytes."}],
            "mappings": [],
        }
        plan_path = cwd / "plan.json"
        for mappings, expected in [([], "blocked"), ([{"claim_id": "preserve", "case_ids": ["case-0"]}], "pass")]:
            plan["mappings"] = mappings
            plan_path.write_text(json.dumps(plan))
            result = assess_scenario_coverage(
                root, source_revision="1" * 40, scenario_set_id="active", coverage_plan=plan
            )
            assert result.status == expected, result.model_dump(mode="json")
            command = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "skills_sdk.cli.main",
                    "eval",
                    "scenario-coverage",
                    str(root),
                    "--source-revision",
                    "1" * 40,
                    "--scenario-set",
                    "active",
                    "--coverage-plan",
                    str(plan_path),
                    "--json",
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
            assert command.returncode == (0 if expected == "pass" else 2), command.stderr
            assert json.loads(command.stdout)["status"] == expected
            assert (root / "SKILL.md").read_bytes() == skill
    print("installed scenario-coverage API and CLI: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
