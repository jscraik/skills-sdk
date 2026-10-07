"""Declared coverage audits through public model, schema, service and CLI seams."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import assess_scenario_coverage
from skills_sdk.evaluation import coverage as coverage_module
from skills_sdk.models.coverage import ScenarioCoveragePlan, ScenarioCoverageResult
from skills_sdk.validation import validate_skill_package

REVISION = "1" * 40


def package_and_plan(directory: Path) -> tuple[Path, dict[str, object]]:
    root = directory / "coverage-fixture"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: coverage-fixture\ndescription: Audit fixtures.\n---\n")
    (root / "references").mkdir()
    cases = [
        {
            "id": f"case-{index}",
            "category": "regression" if index == 0 else "edge" if index == 1 else "happy",
            "unit": "coverage",
            "given": "A checked candidate has declared claims.",
            "should": "Retain all cases and gaps.",
            "realistic": True,
            "why_realistic": "Maintainers audit coverage before execution.",
            "prompt": "Audit the supplied example.",
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
    candidate = validate_skill_package(root, source_revision=REVISION).candidate
    assert candidate is not None
    plan: dict[str, object] = {
        "schema_version": "scenario-coverage-plan/v1",
        "candidate": candidate.model_dump(mode="json"),
        "scenario_set_id": "active",
        "claims": [{"id": "claim-one", "statement": "Preserve the supplied candidate."}],
        "mappings": [{"claim_id": "claim-one", "case_ids": ["case-0"]}],
    }
    return root, plan


def test_public_audit_rejection_and_recovery(tmp_path: Path) -> None:
    root, plan = package_and_plan(tmp_path)
    source = (root / "references/evals.yaml").read_bytes()
    bad = {**plan, "mappings": []}
    blocked = assess_scenario_coverage(root, source_revision=REVISION, scenario_set_id="active", coverage_plan=bad)
    assert blocked.status == "blocked"
    assert "unmapped_claim" in {item.code for item in blocked.findings}
    accepted = assess_scenario_coverage(root, source_revision=REVISION, scenario_set_id="active", coverage_plan=plan)
    assert accepted.status == "pass" and accepted.coverage_complete
    assert len(accepted.active_case_ids) == 10
    assert accepted.candidate == blocked.candidate
    assert not accepted.execution_performed and not accepted.promotion_authorized
    assert (root / "references/evals.yaml").read_bytes() == source
    for result in (blocked, accepted):
        SchemaRegistry().validate("scenario-coverage.v1", result.model_dump(mode="json"))


def test_named_owned_gap_is_retained_not_promoted(tmp_path: Path) -> None:
    root, plan = package_and_plan(tmp_path)
    plan["gaps"] = [{"id": "missing-edge", "reason": "No current boundary case.", "owner": "maintainer"}]
    plan["mappings"] = [{"claim_id": "claim-one", "gap_ids": ["missing-edge"]}]
    result = assess_scenario_coverage(root, source_revision=REVISION, scenario_set_id="active", coverage_plan=plan)
    assert result.status == "pass"
    assert result.open_gap_ids == ("missing-edge",)
    assert not result.coverage_complete
    with pytest.raises(ValidationError):
        ScenarioCoverageResult.model_validate({**result.model_dump(mode="json"), "coverage_complete": True})


@pytest.mark.parametrize("paired_ids", [False, True])
def test_exact_active_case_identifiers_preserve_whitespace(tmp_path: Path, paired_ids: bool) -> None:
    root, plan = package_and_plan(tmp_path)
    path = root / "references/evals.yaml"
    payload = yaml.safe_load(path.read_text())
    index = 1 if paired_ids else 0
    payload["cases"][index]["id"] = " case-0 "
    payload["release_scenario_sets"][0]["cases"][index] = " case-0 "
    path.write_text(yaml.safe_dump(payload))
    source = path.read_bytes()
    plan["candidate"] = validate_skill_package(root, source_revision=REVISION).candidate.model_dump(mode="json")
    plan["mappings"] = [{"claim_id": "claim-one", "case_ids": [" case-0 "]}]
    result = assess_scenario_coverage(root, source_revision=REVISION, scenario_set_id="active", coverage_plan=plan)
    assert result.status == "pass"
    assert " case-0 " in result.active_case_ids
    assert result.plan.mappings[0].case_ids == (" case-0 ",)
    if paired_ids:
        assert "case-0" in result.active_case_ids
    SchemaRegistry().validate("scenario-coverage.v1", result.model_dump(mode="json"))
    assert path.read_bytes() == source


@pytest.mark.parametrize("case_id", ["", " \t\n", 1])
def test_exact_case_identifier_rejects_empty_or_wrong_type(tmp_path: Path, case_id: object) -> None:
    _, plan = package_and_plan(tmp_path)
    plan["mappings"] = [{"claim_id": "claim-one", "case_ids": [case_id]}]
    with pytest.raises(ValidationError):
        ScenarioCoveragePlan.model_validate(plan)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("scenario-coverage-plan.v1", plan)


@pytest.mark.parametrize(
    "mapping",
    [
        {"claim_id": "unknown", "case_ids": ["case-0"]},
        {"claim_id": "claim-one", "case_ids": ["held-out-probe"]},
        {"claim_id": "claim-one", "case_ids": ["case-0", "case-0"]},
        {"claim_id": "claim-one", "gap_ids": ["undeclared"]},
        {"claim_id": "claim-one"},
    ],
)
def test_invalid_mapping_blocks(tmp_path: Path, mapping: dict[str, object]) -> None:
    root, plan = package_and_plan(tmp_path)
    plan["mappings"] = [mapping]
    result = assess_scenario_coverage(root, source_revision=REVISION, scenario_set_id="active", coverage_plan=plan)
    assert result.status == "blocked"
    with pytest.raises(ValidationError):
        ScenarioCoverageResult.model_validate({**result.model_dump(mode="json"), "status": "pass", "findings": []})


def test_stale_candidate_and_forged_plan_block(tmp_path: Path) -> None:
    root, plan = package_and_plan(tmp_path)
    typed = ScenarioCoveragePlan.model_validate(plan)
    object.__setattr__(typed.claims[0], "statement", [])
    invalid = assess_scenario_coverage(root, source_revision=REVISION, scenario_set_id="active", coverage_plan=typed)
    assert invalid.status == "blocked"
    assert "invalid_coverage_plan" in {item.code for item in invalid.findings}
    (root / "SKILL.md").write_text((root / "SKILL.md").read_text() + "Changed source.\n")
    stale = assess_scenario_coverage(root, source_revision=REVISION, scenario_set_id="active", coverage_plan=plan)
    assert stale.status == "blocked"
    assert "coverage_identity_mismatch" in {item.code for item in stale.findings}


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": True},
        {"claims": []},
        {"scenario_set_id": "other"},
        {"gaps": [{"id": "unused", "reason": "Needs proof.", "owner": "maintainer"}]},
        {"gaps": [{"id": "unowned", "reason": "Needs proof."}]},
        {"mappings": [{"claim_id": "claim-one", "case_ids": ["case-0"]}] * 2},
    ],
)
def test_malformed_or_contradictory_plan_blocks(tmp_path: Path, change: dict[str, object]) -> None:
    root, plan = package_and_plan(tmp_path)
    result = assess_scenario_coverage(
        root, source_revision=REVISION, scenario_set_id="active", coverage_plan={**plan, **change}
    )
    assert result.status == "blocked"
    assert not result.coverage_complete


def test_candidate_change_during_audit_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, plan = package_and_plan(tmp_path)
    original = coverage_module.validate_skill_package
    calls = 0

    def changing_validation(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            skill = root / "SKILL.md"
            skill.write_text(skill.read_text() + "Changed during audit.\n")
        return original(*args, **kwargs)

    monkeypatch.setattr(coverage_module, "validate_skill_package", changing_validation)
    result = assess_scenario_coverage(root, source_revision=REVISION, scenario_set_id="active", coverage_plan=plan)
    assert result.status == "blocked"
    assert "candidate_changed" in {item.code for item in result.findings}


@pytest.mark.parametrize("json_output", [False, True])
def test_cli_safe_plan_read_and_corrected_input(tmp_path: Path, json_output: bool) -> None:
    root, plan = package_and_plan(tmp_path)
    path = tmp_path / "plan.json"
    args = [
        sys.executable,
        "-m",
        "skills_sdk.cli.main",
        "eval",
        "scenario-coverage",
        str(root),
        "--source-revision",
        REVISION,
        "--scenario-set",
        "active",
        "--coverage-plan",
        str(path),
    ]
    if json_output:
        args.append("--json")
    for data, expected in [("{", 2), (json.dumps(plan), 0)]:
        path.write_text(data)
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        assert result.returncode == expected, result.stderr
        status = "pass" if expected == 0 else "blocked"
        if json_output:
            assert json.loads(result.stdout)["status"] == status
        else:
            assert result.stdout.startswith(f"scenario-coverage: {status} (")
            assert "Traceback" not in result.stderr
    saved = tmp_path / "saved.json"
    path.rename(saved)
    path.symlink_to(saved)
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 2
    if json_output:
        assert json.loads(result.stdout)["status"] == "blocked"
    else:
        assert result.stdout.startswith("scenario-coverage: blocked (")
        assert "Traceback" not in result.stderr
