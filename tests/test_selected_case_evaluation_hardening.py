"""Regression coverage for selected-case evidence boundary hardening."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from test_selected_case_evaluation import REVISION, _adapter, _evidence, _prepared_request, _skill

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.selected_case import execute_selected_case, load_selected_case
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence


@pytest.mark.parametrize("evidence_ref", ["evidence/eyJabc.def.ghi.json", "evidence/client_secret.json"])
def test_judge_evidence_model_matches_schema_credential_screening(tmp_path: Path, evidence_ref: str) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload["evidence_refs"] = [evidence_ref]

    with pytest.raises(ValueError, match="credential-shaped"):
        SelectedCaseJudgeEvidence.model_validate(payload)
    schema = SchemaRegistry().load("selected-case-judge-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_unserializable_forged_judge_evidence_returns_typed_blocker(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "behavior"
    forged = _evidence(definition, request, output).model_copy(update={"evidence_refs": (object(),)})

    receipt = asyncio.run(execute_selected_case(definition, request, input_payload, _adapter(request, output), forged))

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "invalid_judge_evidence"


def test_existing_judge_result_ref_is_not_duplicated(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "behavior"
    evidence = _evidence(definition, request, output)
    judge_result_ref = f"judge-results/{evidence.judge_result_sha256}"
    evidence = evidence.model_copy(update={"evidence_refs": (judge_result_ref,)})

    receipt = asyncio.run(
        execute_selected_case(definition, request, input_payload, _adapter(request, output), evidence)
    )

    assert receipt.status == "pass"
    assert receipt.case_results[0].evidence_refs == (judge_result_ref,)


@pytest.mark.parametrize("missing_field", ["deterministic_checks", "forbidden_commands"])
def test_selected_case_requires_declared_deterministic_checks(tmp_path: Path, missing_field: str) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    case = payload["cases"][0]
    if missing_field == "deterministic_checks":
        case.pop(missing_field)
    else:
        case["deterministic_checks"].pop(missing_field)
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid_selected_case"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_selected_case_accepts_explicit_empty_forbidden_commands(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["deterministic_checks"]["forbidden_commands"] = []
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")

    assert definition.scenario_set.cases[0].forbidden_commands == ()
