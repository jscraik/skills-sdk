"""CircleCI command and trusted metadata regression guards."""

from pathlib import Path

import pytest
import yaml

from scripts.check_repository_standards import _circleci_findings

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_circleci_requires_trusted_base_without_candidate_fallback() -> None:
    workflow = (REPOSITORY_ROOT / "scripts/circleci_pr_contract.sh").read_text(encoding="utf-8")
    assert 'git show "$BASE_SHA:.github/scripts/validate_pr_template_body.py"' in workflow
    assert "validator=.github/scripts/validate_pr_template_body.py" not in workflow


@pytest.mark.parametrize(
    "damage,expected",
    [
        ("base", "pr-template"),
        ("phase", "ci-validation"),
        ("order", "ci-contract"),
        ("comment-prepare", "ci-contract"),
        ("comment-checksum", "ci-tooling"),
        ("comment-phase", "ci-validation"),
    ],
)
def test_circleci_contract_rejects_missing_trust_proof_and_bad_order(
    tmp_path: Path, damage: str, expected: str
) -> None:
    config = tmp_path / ".circleci/config.yml"
    config.parent.mkdir()
    text = (REPOSITORY_ROOT / ".circleci/config.yml").read_text()
    script = tmp_path / "scripts/circleci_pr_contract.sh"
    script.parent.mkdir()
    contract = (REPOSITORY_ROOT / "scripts/circleci_pr_contract.sh").read_text()
    if damage == "base":
        contract = contract.replace('git show "$BASE_SHA:.github/scripts/validate_pr_template_body.py"', "false")
    elif damage == "phase":
        text = text.replace("bash scripts/validate-repository.sh installed", "false")
    elif damage.startswith("comment-"):
        fragment = {
            "comment-prepare": "bash scripts/circleci_pr_contract.sh",
            "comment-checksum": "sha256sum -c -",
            "comment-phase": "bash scripts/validate-repository.sh installed",
        }[damage]
        parsed = yaml.safe_load(text)
        for step in parsed["jobs"]["validate"]["steps"]:
            if isinstance(step, dict) and isinstance(step.get("run"), dict):
                command = step["run"]["command"]
                step["run"]["command"] = "\n".join(
                    "# " + line if fragment in line else line for line in command.splitlines()
                )
        text = yaml.safe_dump(parsed)
    else:
        parsed = yaml.safe_load(text)
        steps = parsed["jobs"]["validate"]["steps"]
        steps[1], steps[3] = steps[3], steps[1]
        text = yaml.safe_dump(parsed)
    config.write_text(text)
    script.write_text(contract)
    findings, enforced = _circleci_findings(tmp_path)
    assert any(finding.code == expected for finding in findings)
    assert enforced is (damage != "base")
