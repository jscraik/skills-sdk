"""One candidate-bound offline intake-to-check journey through the public CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_scorer_assessment import _package

from skills_sdk.cli.main import main
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import assess_scorer_quality
from skills_sdk.models.local_check import LocalCheckResult

REVISION = "1" * 40


def _fixture(root: Path) -> tuple[Path, Path]:
    """Write a synthetic ten-case package and intake context, returning their paths."""
    package = _package(root)
    evals_path = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    ids = [f"case-{index}" for index in range(10)]
    payload["release_scenario_sets"] = [
        {
            "id": "active-ten",
            "minimum_scenarios": 10,
            "target_scenarios": 10,
            "maximum_scenarios": 10,
            "groups": {"regular": ids[:8], "safety": ids[8:]},
        }
    ]
    payload["cases"] = [
        {
            "id": case_id,
            "category": "pressure" if index >= 8 else "edge" if index == 7 else "happy",
            "unit": "local check",
            "given": "A complete candidate is supplied.",
            "should": "Assess package-local evidence without executing a provider.",
            "realistic": True,
            "why_realistic": "Maintainers need a bounded preflight before any live evaluation.",
            "prompt": "Review this bounded candidate.",
            "reproduce": "skills-sdk check-local example",
            "eval_modes": ["release"],
            "deterministic_checks": {"forbidden_commands": ["rm -rf"]},
            "acceptance": [{"type": "expected_signal", "value": "bounded result"}],
        }
        for index, case_id in enumerate(ids)
    ]
    evals_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    context = root / "context.json"
    context.write_text(
        json.dumps(
            {
                "schema_version": "skill-package-intake-context/v1",
                "source_repository": "jscraik/skills-sdk",
                "source_revision": REVISION,
                "source_path": "tests/fixtures/synthetic-skill",
                "source_kind": "git",
                "owner": {
                    "schema_version": "package-owner/v1",
                    "owner": "sdk-tests",
                    "maintainer": "sdk-tests",
                    "ownership_state": "canonical",
                    "rights": {
                        "basis": "authored",
                        "license": "Apache-2.0",
                        "evidence_ref": "tests/fixtures/synthetic-skill/SKILL.md",
                    },
                },
                "checks": {"identity": True, "provenance": True, "rights": True, "owner_unchanged": True},
            }
        ),
        encoding="utf-8",
    )
    return package, context


def _command(package: Path, context: Path) -> list[str]:
    """Build JSON CLI arguments for the fixture's explicit ten-case scenario set."""
    return ["check-local", str(package), "--context", str(context), "--scenario-set", "active-ten", "--json"]


def test_local_check_accepts_rejects_and_recovers_without_promotion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify scenario-count rejection and recovery preserve candidate binding and deny promotion."""
    package, context = _fixture(tmp_path)
    command = _command(package, context)
    assert main(command) == 0
    accepted = json.loads(capsys.readouterr().out)
    assert accepted["schema_version"] == "local-check/v1"
    SchemaRegistry().validate("local-check.v1", accepted)
    assert accepted["status"] == "local_checks_passed"
    assert [stage["name"] for stage in accepted["stages"]] == [
        "intake",
        "validate",
        "scenario-quality",
        "scorer-quality",
        "scorer-calibration",
    ]
    assert len({stage["receipt"]["candidate"]["content_sha256"] for stage in accepted["stages"]}) == 1
    assert accepted["promotion_authorized"] is accepted["execution_performed"] is False

    evals_path = package / "references" / "evals.yaml"
    original = evals_path.read_text(encoding="utf-8")
    payload = yaml.safe_load(original)
    payload["release_scenario_sets"][0]["target_scenarios"] = 8
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    assert main(command) == 2
    rejected = json.loads(capsys.readouterr().out)
    SchemaRegistry().validate("local-check.v1", rejected)
    assert rejected["blocked_stage"] == "scenario-quality"
    assert [stage["name"] for stage in rejected["stages"]] == ["intake", "validate", "scenario-quality"]
    evals_path.write_text(original, encoding="utf-8")
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "local_checks_passed"


def test_local_check_envelope_rejects_unknown_fields_and_false_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reject unknown envelope fields and success claims with incomplete stage evidence."""
    package, context = _fixture(tmp_path)
    assert main(_command(package, context)) == 0
    accepted = json.loads(capsys.readouterr().out)
    registry = SchemaRegistry()
    with pytest.raises(ContractError):
        registry.validate("local-check.v1", {**accepted, "unknown": True})
    with pytest.raises(ContractError):
        registry.validate("local-check.v1", {**accepted, "stages": accepted["stages"][:-1]})
    direct = Draft202012Validator(registry.load("local-check.v1"))
    assert direct.is_valid(accepted)
    assert not direct.is_valid({"status": "local_checks_passed"})
    assert not direct.is_valid({**accepted, "stages": accepted["stages"][:-1]})
    assert not direct.is_valid({**accepted, "stages": list(reversed(accepted["stages"]))})


def test_local_check_envelope_rejects_earlier_blocker_before_candidate_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package, context = _fixture(tmp_path)
    command = _command(package, context)
    assert main(command) == 0
    accepted = json.loads(capsys.readouterr().out)
    evals_path = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    payload["release_scenario_sets"][0]["target_scenarios"] = 8
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    assert main(command) == 2
    blocked = json.loads(capsys.readouterr().out)
    later_stage = accepted["stages"][3]
    later_stage["receipt"]["candidate"]["content_sha256"] = "0" * 64
    blocked["stages"].append(later_stage)
    blocked["blocked_stage"] = "candidate_changed"
    with pytest.raises(ContractError):
        SchemaRegistry().validate("local-check.v1", blocked)


def test_local_check_revalidates_altered_stage_instances(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package, context = _fixture(tmp_path)
    assert main(_command(package, context)) == 0
    accepted = LocalCheckResult.model_validate(json.loads(capsys.readouterr().out))
    forged = accepted.stages[1].model_copy(update={"receipt": accepted.stages[3].receipt})
    stages = (accepted.stages[0], forged, *accepted.stages[2:])
    with pytest.raises(ValidationError):
        LocalCheckResult(status="local_checks_passed", candidate=accepted.candidate, stages=stages)


def test_local_check_revalidates_altered_receipt_instances(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package, context = _fixture(tmp_path)
    assert main(_command(package, context)) == 0
    accepted = LocalCheckResult.model_validate(json.loads(capsys.readouterr().out))
    forged_receipt = accepted.stages[3].receipt.model_copy(update={"calibration_probe_count": 0})
    forged_stage = accepted.stages[3].model_copy(update={"receipt": forged_receipt})
    stages = (*accepted.stages[:3], forged_stage, accepted.stages[4])
    with pytest.raises(ValidationError):
        LocalCheckResult(status="local_checks_passed", candidate=accepted.candidate, stages=stages)


def test_local_check_safe_context_read_unavailable_is_typed_blocker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Return a typed context blocker when safe context reads are unavailable."""
    import skills_sdk.cli.main as cli

    package, context = _fixture(tmp_path)

    def unavailable(_: Path) -> bytes:
        """Simulate a platform that cannot safely read the intake context."""
        raise cli._UnsupportedContextRead("unsupported")

    monkeypatch.setattr(cli, "_read_intake_context", unavailable)
    assert main(_command(package, context)) == 2
    blocked = json.loads(capsys.readouterr().out)
    SchemaRegistry().validate("local-check.v1", blocked)
    assert blocked["status"] == "blocked"
    assert blocked["blocked_stage"] == "context"
    assert blocked["stages"] == []
    assert blocked["blocker"]["code"] == "unsupported_context_read"


def test_local_check_stops_before_evaluation_on_non_admit_intake(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stop after intake when an ownership change requires an owner decision."""
    package, context = _fixture(tmp_path)
    payload = json.loads(context.read_text(encoding="utf-8"))
    payload["checks"]["owner_unchanged"] = False
    context.write_text(json.dumps(payload), encoding="utf-8")
    assert main(_command(package, context)) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["blocked_stage"] == "intake"
    assert [stage["name"] for stage in blocked["stages"]] == ["intake"]
    assert blocked["stages"][0]["receipt"]["decision"]["decision"] == "needs_owner_decision"
    assert blocked["promotion_authorized"] is False


def test_local_check_human_output_explains_blocked_intake_and_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package, context = _fixture(tmp_path)
    command = _command(package, context)[:-1]
    payload = json.loads(context.read_text(encoding="utf-8"))
    payload["checks"]["owner_unchanged"] = False
    context.write_text(json.dumps(payload), encoding="utf-8")
    assert main(command) == 2
    intake_output = capsys.readouterr().out
    assert "decision: needs_owner_decision" in intake_output
    assert "decision_blocker:" in intake_output
    payload["checks"]["owner_unchanged"] = True
    context.write_text(json.dumps(payload), encoding="utf-8")
    evals_path = package / "references" / "evals.yaml"
    evals_path.write_text(
        evals_path.read_text(encoding="utf-8").replace("short_correct_wins", "verbose_wrong_wins"),
        encoding="utf-8",
    )
    assert main(command) == 2
    check_output = capsys.readouterr().out
    assert "blocked_stage: scorer-quality" in check_output
    assert "calibration_expected_outcomes:" in check_output


def test_local_check_rejects_candidate_change_between_stages(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Block validation when the package changes after intake."""
    import skills_sdk.validation as validation

    package, context = _fixture(tmp_path)
    original_validate = validation.validate_skill_package

    def changed_candidate(*args: object, **kwargs: object) -> object:
        """Mutate the entrypoint before validation to produce a different candidate digest."""
        entrypoint = package / "SKILL.md"
        entrypoint.write_text(entrypoint.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(validation, "validate_skill_package", changed_candidate)
    assert main(_command(package, context)) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["blocked_stage"] == "candidate_changed"
    assert [stage["name"] for stage in blocked["stages"]] == ["intake", "validate"]
    assert blocked["promotion_authorized"] is False


@pytest.mark.parametrize(
    ("file_name", "mutate", "blocked_stage"),
    [
        ("references/evals.yaml", "invalid_direction", "scorer-quality"),
        ("references/scorer-calibration/manifest.json", "wrong_scorer", "scorer-calibration"),
    ],
)
def test_local_check_stops_at_scorer_stage_and_recovers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], file_name: str, mutate: str, blocked_stage: str
) -> None:
    """Stop at the failing scorer stage and recover after its input is restored."""
    package, context = _fixture(tmp_path)
    path = package / file_name
    original = path.read_text(encoding="utf-8")
    if mutate == "invalid_direction":
        path.write_text(original.replace("short_correct_wins", "verbose_wrong_wins"), encoding="utf-8")
    else:
        payload = json.loads(original)
        payload["scorer_id"] = "other-scorer"
        path.write_text(json.dumps(payload), encoding="utf-8")
    command = _command(package, context)
    assert main(command) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["blocked_stage"] == blocked_stage
    assert blocked["stages"][-1]["receipt"]["status"] == "blocked"
    path.write_text(original, encoding="utf-8")
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "local_checks_passed"


@pytest.mark.parametrize(
    ("label", "score", "expected_status"),
    [
        ("fail", 0.2, "pass"),
        ("pass", 0.2, "blocked"),
        ("fail", 0.95, "blocked"),
        ("fail", None, "blocked"),
        (None, 0.2, "blocked"),
    ],
)
def test_directional_probe_accepts_consistent_losing_candidate_outcome(
    tmp_path: Path, label: str | None, score: float | None, expected_status: str
) -> None:
    """Accept a consistent losing-candidate outcome and reject contradictory labels or scores."""
    package = _package(tmp_path)
    evals_path = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    case = next(
        item
        for item in payload["scorer_quality"]["calibration_cases"]
        if item["probe_type"] == "short_correct_vs_verbose_wrong"
    )
    case.update(expected_label=label, expected_score=score)
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    result = assess_scorer_quality(package, source_revision=REVISION)
    assert result.status == expected_status
    assert ("calibration_expected_outcomes" in {finding.code for finding in result.findings}) is (
        expected_status == "blocked"
    )
