"""CircleCI command and trusted metadata regression guards."""

from pathlib import Path

import pytest
import yaml

from scripts.check_repository_standards import _circleci_findings
from scripts.circleci_standards import _invokes

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("terminator", ["exit 0", "exec true"])
@pytest.mark.parametrize(
    "required",
    [
        "bash scripts/circleci_pr_contract.sh",
        "mise install python uv ruff vale",
        "bash scripts/validate-repository.sh quality",
    ],
)
def test_required_commands_must_precede_shell_termination(terminator: str, required: str) -> None:
    """Retain reachable commands but never count lines after shell termination."""
    assert not _invokes(f"{terminator}\n{required}", required)
    assert _invokes(f"{required}\n{terminator}", required)


def test_circleci_requires_trusted_base_without_candidate_fallback() -> None:
    workflow = (REPOSITORY_ROOT / "scripts/circleci_pr_contract.sh").read_text(encoding="utf-8")
    assert 'git show "$BASE_SHA:.github/scripts/validate_pr_template_body.py"' in workflow
    assert "validator=.github/scripts/validate_pr_template_body.py" not in workflow


@pytest.mark.parametrize(
    "damage,expected",
    [
        ("base", "pr-template"),
        ("unscheduled", "pr-template"),
        ("filtered", "pr-template"),
        ("conditional", "pr-template"),
        ("phase", "ci-validation"),
        ("order", "ci-contract"),
        ("comment-prepare", "ci-contract"),
        ("comment-checksum", "ci-tooling"),
        ("comment-phase", "ci-validation"),
        ("echo-prepare", "ci-contract"),
        ("echo-phase", "ci-validation"),
        ("checksum-noop", "ci-tooling"),
        ("checksum-quoted-pipe", "ci-tooling"),
        ("failure-only-prepare", "ci-contract"),
        ("failure-only-phase", "ci-validation"),
        ("false-prepare", "ci-contract"),
        ("false-checksum", "ci-tooling"),
        ("false-phase", "ci-validation"),
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
    elif damage in {"unscheduled", "filtered", "conditional"}:
        parsed = yaml.safe_load(text)
        workflow = parsed["workflows"]["validation"]
        if damage == "unscheduled":
            workflow["jobs"] = []
        elif damage == "filtered":
            workflow["jobs"] = [{"validate": {"filters": {"branches": {"only": "main"}}}}]
        else:
            workflow["when"] = False
        text = yaml.safe_dump(parsed)
    elif damage.startswith("failure-only-") or damage.startswith("false-"):
        parsed = yaml.safe_load(text)
        fragment = {
            "failure-only-prepare": "bash scripts/circleci_pr_contract.sh",
            "failure-only-phase": "bash scripts/validate-repository.sh installed",
            "false-prepare": "bash scripts/circleci_pr_contract.sh",
            "false-checksum": "sha256sum -c -",
            "false-phase": "bash scripts/validate-repository.sh installed",
        }[damage]
        for step in parsed["jobs"]["validate"]["steps"]:
            if isinstance(step, dict) and isinstance(step.get("run"), dict):
                run = step["run"]
                if fragment in run["command"]:
                    if damage.startswith("failure-only-"):
                        run["when"] = "on_fail"
                    else:
                        run["command"] = "if false; then\n" + run["command"] + "\nfi"
        text = yaml.safe_dump(parsed)
    elif damage == "echo-prepare":
        text = text.replace("bash scripts/circleci_pr_contract.sh", "echo bash scripts/circleci_pr_contract.sh")
    elif damage == "echo-phase":
        text = text.replace(
            "bash scripts/validate-repository.sh installed", "echo bash scripts/validate-repository.sh installed"
        )
    elif damage == "checksum-noop":
        text = text.replace("sha256sum -c -", "sha256sum -c - || true")
    elif damage == "checksum-quoted-pipe":
        text = text.replace(" | sha256sum", ' "|" sha256sum')
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
    assert enforced is (damage not in {"base", "unscheduled", "filtered", "conditional"})
