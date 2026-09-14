from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import ScenarioQualityPolicy, assess_scenario_quality
from skills_sdk.evaluation import quality as quality_module

REVISION = "1" * 40


def _case(case_id: str = "happy", *, category: str = "happy") -> dict[str, object]:
    return {
        "id": case_id,
        "category": category,
        "unit": "portable quality",
        "given": "A candidate has package-local scenarios.",
        "should": "Assess the definitions deterministically.",
        "realistic": True,
        "why_realistic": "Maintainers need pre-execution quality proof.",
        "prompt": "Review this bounded candidate.",
        "reproduce": "skills-sdk eval scenario-quality . --source-revision <revision>",
        "eval_modes": ["smoke", "release"],
        "deterministic_checks": {"forbidden_commands": ["rm -rf"]},
        "acceptance": [{"type": "expected_signal", "value": "bounded result"}],
    }


def _skill(root: Path, payload: dict[str, object]) -> Path:
    root.mkdir()
    (root / "SKILL.md").write_text(
        f"---\nname: {root.name}\ndescription: Example skill.\n---\n",
        encoding="utf-8",
    )
    references = root / "references"
    references.mkdir()
    (references / "evals.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return root


def test_assessment_passes_valid_neighbor_without_mutation(tmp_path: Path) -> None:
    root = _skill(tmp_path / "example", {"schema_version": "2.0", "skill_name": "example", "cases": [_case()]})
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    first = assess_scenario_quality(root, source_revision=REVISION)
    second = assess_scenario_quality(root, source_revision=REVISION)
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    assert first == second
    assert first.status == "pass"
    assert first.scenario_count == 1
    assert first.mutation_performed is first.network_used is first.execution_performed is False
    assert before == after
    SchemaRegistry().validate("scenario-quality.v1", first.model_dump(mode="json"))


def test_field_obligations_require_field_aware_assertions(tmp_path: Path) -> None:
    case = _case()
    case["output_contract"] = {"required_fields": ["outcome"]}
    blocked = assess_scenario_quality(
        _skill(tmp_path / "example", {"schema_version": "2.0", "skill_name": "example", "cases": [case]}),
        source_revision=REVISION,
    )
    assert blocked.status == "blocked"
    assert [finding.code for finding in blocked.findings] == ["missing_field_assertion"]

    case["acceptance"] = [{"type": "text_field_equals", "field": "outcome", "value": "pass"}]
    assert (
        assess_scenario_quality(
            _skill(tmp_path / "neighbor", {"schema_version": "2.0", "skill_name": "neighbor", "cases": [case]}),
            source_revision=REVISION,
        ).status
        == "pass"
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda payload: payload["cases"].append(_case()), "duplicate_scenario_id"),
        (lambda payload: payload["cases"][0].update({"unknown": True}), "unsupported_scenario_field"),
        (
            lambda payload: payload["cases"][0].update({"acceptance": [{"type": "unknown"}]}),
            "unsupported_acceptance_assertion",
        ),
    ],
)
def test_invalid_definition_neighbors_are_typed(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    code: str,
) -> None:
    payload: dict[str, Any] = {"schema_version": "2.0", "skill_name": "example", "cases": [_case()]}
    mutation(payload)
    result = assess_scenario_quality(_skill(tmp_path / "example", payload), source_revision=REVISION)
    assert result.status == "blocked"
    assert code in {finding.code for finding in result.findings}


def test_release_policy_is_explicit_and_selector_scoped(tmp_path: Path) -> None:
    cases = [_case(f"case-{index}", category="happy") for index in range(8)]
    cases[6]["category"] = "pressure"
    cases[7]["category"] = "edge"
    payload = {
        "schema_version": "2.0",
        "skill_name": "example",
        "release_scenario_sets": [{"id": "release", "groups": {"all": [case["id"] for case in cases]}}],
        "cases": cases,
    }
    root = _skill(tmp_path / "example", payload)
    assert assess_scenario_quality(root, source_revision=REVISION, scenario_set_id="release").status == "pass"
    blocked = assess_scenario_quality(
        root,
        source_revision=REVISION,
        scenario_set_id="release",
        policy=ScenarioQualityPolicy(minimum_release_cases=9),
    )
    assert {finding.code for finding in blocked.findings} == {"release_case_floor"}
    assert assess_scenario_quality(root, source_revision=REVISION, scenario_set_id="missing").status == "blocked"


def test_malformed_yaml_aliases_duplicate_keys_and_invalid_revision_block(tmp_path: Path) -> None:
    for name, text in (
        ("malformed", "schema_version: [unterminated\n"),
        ("duplicate", "schema_version: '2.0'\nskill_name: one\nskill_name: two\ncases: []\n"),
        ("alias", "schema_version: '2.0'\nskill_name: &name one\ncases: [*name]\n"),
    ):
        root = _skill(tmp_path / name, {"cases": [_case()]})
        (root / "references/evals.yaml").write_text(text, encoding="utf-8")
        assert assess_scenario_quality(root, source_revision=REVISION).status == "blocked"
    result = assess_scenario_quality(tmp_path / "duplicate", source_revision="invalid")
    assert result.status == "blocked"
    assert result.candidate is None
    assert result.findings[0].code == "invalid_source_revision"


def test_changed_candidate_snapshot_is_a_typed_blocker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _skill(tmp_path / "example", {"schema_version": "2.0", "skill_name": "example", "cases": [_case()]})

    def changed(_: Path, __: str) -> bytes:
        raise ValueError("evals_source_changed")

    monkeypatch.setattr(quality_module, "_capture_evals", changed)
    result = assess_scenario_quality(root, source_revision=REVISION)
    assert result.status == "blocked"
    assert result.findings[0].code == "evals_source_changed"


def test_capture_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    root = tmp_path / "example"
    references = root / "references"
    references.mkdir(parents=True)
    os.mkfifo(references / "evals.yaml")

    with pytest.raises(ValueError, match="invalid_evals_file_type"):
        quality_module._capture_evals(root, "0" * 64)


def test_validation_blocker_preserves_upstream_evidence_refs(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    result = assess_scenario_quality(root, source_revision=REVISION)

    assert result.blocker is not None
    assert result.findings[0].evidence_refs == result.blocker.evidence_refs
    assert result.findings[0].evidence_refs != ("references/evals.yaml",)


def test_untrusted_mapping_key_returns_a_typed_blocker_through_service_and_cli(tmp_path: Path) -> None:
    root = _skill(tmp_path / "example", {"cases": [_case()]})
    (root / "references/evals.yaml").write_text("? [a, b]\n: value\n", encoding="utf-8")

    result = assess_scenario_quality(root, source_revision=REVISION)
    assert result.status == "blocked"
    assert result.findings[0].code == "invalid_evals_yaml"
    completed = subprocess.run(
        ["skills-sdk", "eval", "scenario-quality", str(root), "--source-revision", REVISION, "--json", "--robot"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 2, completed.stderr
    assert json.loads(completed.stdout)["findings"][0]["code"] == "invalid_evals_yaml"


def test_assertion_payloads_are_closed_and_field_obligations_need_real_proof(tmp_path: Path) -> None:
    case = _case()
    case["output_contract"] = {"required_fields": ["outcome"]}
    case["acceptance"] = [{"type": "text_field_equals", "field": "outcome"}]
    result = assess_scenario_quality(
        _skill(tmp_path / "example", {"schema_version": "2.0", "skill_name": "example", "cases": [case]}),
        source_revision=REVISION,
    )
    assert {finding.code for finding in result.findings} == {
        "invalid_acceptance_assertion",
        "missing_field_assertion",
    }

    case["acceptance"] = [{"type": "text_field_equals", "field": "outcome", "value": "pass", "unexpected": True}]
    case["output_contract"] = {"required_fields": ["outcome"], "unexpected": True}
    result = assess_scenario_quality(
        _skill(tmp_path / "neighbor", {"schema_version": "2.0", "skill_name": "neighbor", "cases": [case]}),
        source_revision=REVISION,
    )
    assert {finding.code for finding in result.findings} == {
        "invalid_acceptance_assertion",
        "invalid_output_contract",
    }


def test_release_selection_rejects_smoke_only_cases(tmp_path: Path) -> None:
    cases = [_case(f"case-{index}") for index in range(8)]
    cases[6]["category"] = "pressure"
    cases[7]["category"] = "edge"
    for case in cases:
        case["eval_modes"] = ["smoke"]
    payload = {
        "schema_version": "2.0",
        "skill_name": "example",
        "release_scenario_sets": [{"id": "release", "groups": {"all": [case["id"] for case in cases]}}],
        "cases": cases,
    }
    result = assess_scenario_quality(
        _skill(tmp_path / "example", payload),
        source_revision=REVISION,
        scenario_set_id="release",
    )
    assert {finding.code for finding in result.findings} == {"release_case_not_eligible"}


@pytest.mark.parametrize("groups", [{"all": "case-0"}, {"all": [1]}, ["case-0"]])
def test_release_selector_rejects_malformed_groups_and_ids(tmp_path: Path, groups: object) -> None:
    payload = {
        "schema_version": "2.0",
        "skill_name": "example",
        "release_scenario_sets": [{"id": "release", "groups": groups}],
        "cases": [_case("case-0")],
    }
    result = assess_scenario_quality(
        _skill(tmp_path / "example", payload),
        source_revision=REVISION,
        scenario_set_id="release",
    )

    assert "invalid_scenario_set" in {finding.code for finding in result.findings}


def test_release_selection_reports_duplicate_source_and_selector_ids(tmp_path: Path) -> None:
    first = _case("duplicate", category="pressure")
    second = _case("duplicate", category="edge")
    payload = {
        "schema_version": "2.0",
        "skill_name": "example",
        "release_scenario_sets": [{"id": "release", "groups": {"all": ["duplicate", "duplicate"]}}],
        "cases": [first, second],
    }
    result = assess_scenario_quality(
        _skill(tmp_path / "example", payload),
        source_revision=REVISION,
        scenario_set_id="release",
        policy=ScenarioQualityPolicy(minimum_release_cases=0),
    )

    assert [finding.code for finding in result.findings].count("duplicate_scenario_id") == 2


@pytest.mark.parametrize(
    ("schema_version", "skill_name", "code"),
    [("1.0", "example", "unsupported_evals_schema"), ("2.0", "other", "skill_name_mismatch")],
)
def test_evals_identity_matches_candidate(
    tmp_path: Path,
    schema_version: str,
    skill_name: str,
    code: str,
) -> None:
    result = assess_scenario_quality(
        _skill(
            tmp_path / "example",
            {"schema_version": schema_version, "skill_name": skill_name, "cases": [_case()]},
        ),
        source_revision=REVISION,
    )
    assert code in {finding.code for finding in result.findings}


def test_cli_executes_real_json_route(tmp_path: Path) -> None:
    root = _skill(tmp_path / "example", {"schema_version": "2.0", "skill_name": "example", "cases": [_case()]})
    completed = subprocess.run(
        ["skills-sdk", "eval", "scenario-quality", str(root), "--source-revision", REVISION, "--json", "--robot"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["schema_version"] == "scenario-quality/v1"


def test_cli_human_output_prints_every_scenario_finding(tmp_path: Path) -> None:
    case = _case()
    case.pop("given")
    case.pop("should")
    root = _skill(tmp_path / "example", {"schema_version": "2.0", "skill_name": "example", "cases": [case]})
    completed = subprocess.run(
        ["skills-sdk", "eval", "scenario-quality", str(root), "--source-revision", REVISION, "--robot"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    assert completed.stdout.count("missing_scenario_field") == 2


def test_cli_requires_an_eval_lane() -> None:
    completed = subprocess.run(
        ["skills-sdk", "eval"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 2
    assert "required" in completed.stderr
