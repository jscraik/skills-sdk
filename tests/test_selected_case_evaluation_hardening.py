"""Regression coverage for selected-case evidence boundary hardening."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from test_selected_case_evaluation import REVISION, _adapter, _evidence, _prepared_request, _skill

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.selected_case import execute_selected_case, load_selected_case
from skills_sdk.models.provider_execution import ProviderExecutionRequest
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
    assert receipt.case_results[0].evidence_refs.count(judge_result_ref) == 1


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


def test_provider_output_evidence_survives_selected_case_receipt(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "reviewed behavior"
    receipt = asyncio.run(
        execute_selected_case(
            definition, request, input_payload, _adapter(request, output), _evidence(definition, request, output)
        )
    )
    assert "evidence/provider-output.json" in receipt.case_results[0].evidence_refs


@pytest.mark.parametrize("mode_list", [["release", "standard"], ["release", "release"], ["release", []], []])
def test_selected_case_rejects_invalid_declared_modes(tmp_path: Path, mode_list: list[object]) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["eval_modes"] = mode_list
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="selected_case_mode_mismatch"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize("field", ["case_id", "scenario_set_id", "satisfied_assertion_ids"])
def test_judge_identity_fields_reject_padding(tmp_path: Path, field: str) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    if field == "satisfied_assertion_ids":
        payload[field][0] = f" {payload[field][0]} "
    else:
        payload[field] = f" {payload[field]} "
    with pytest.raises(ValueError, match="normalized"):
        SelectedCaseJudgeEvidence.model_validate(payload)


@pytest.mark.parametrize("field", ["case_id", "scenario_set_id", "satisfied_assertion_ids"])
def test_judge_identity_fields_reject_private_values_in_model_and_schema(tmp_path: Path, field: str) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    if field == "satisfied_assertion_ids":
        payload[field][0] = "ghp_secret"
    else:
        payload[field] = "ghp_secret"
    with pytest.raises(ValueError, match="credential-shaped"):
        SelectedCaseJudgeEvidence.model_validate(payload)
    schema = SchemaRegistry().load("selected-case-judge-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize("requirement_id", ["ghp_secret", " preserve_behavior "])
def test_selected_case_rejects_private_or_padded_requirement_ids(tmp_path: Path, requirement_id: str) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"] = [
        {"type": "semantic_requirements", "requirements": [{"id": requirement_id, "all_of": ["behavior"]}]}
    ]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid_acceptance_assertion"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_blocked_provider_request_returns_bound_receipt_without_adapter(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    prepared = _prepared_request(definition, input_payload)
    payload = prepared.model_dump(mode="json")
    payload["status"] = "blocked"
    payload["blocker"] = {"code": "safety_unavailable", "category": "safety", "evidence_refs": ["evidence/safety.json"]}
    blocked = ProviderExecutionRequest.model_validate(payload)

    receipt = asyncio.run(execute_selected_case(definition, blocked, input_payload, None, None))

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "safety_unavailable"
    assert receipt.case_results[0].blocker.evidence_refs == ("evidence/safety.json",)


def test_mismatched_judge_binding_blocks_before_adapter_call(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    evidence = _evidence(definition, request, "reviewed").model_copy(update={"assertion_contract_sha256": "d" * 64})

    class NeverCallAdapter:
        descriptor = _adapter(request, "reviewed").descriptor

        async def complete(self, request: object, input_payload: object) -> None:
            raise AssertionError("adapter must not be called")

        async def cleanup(self) -> None:
            return None

    receipt = asyncio.run(execute_selected_case(definition, request, input_payload, NeverCallAdapter(), evidence))

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_identity_mismatch"


def test_forged_provider_request_is_rejected_before_blocked_receipt(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    forged_provider = request.provider.model_copy(update={"model_id": "ghp_secret"})
    forged_request = request.model_copy(update={"provider": forged_provider, "status": "blocked"})

    with pytest.raises(ContractError, match="invalid_provider_request"):
        asyncio.run(execute_selected_case(definition, forged_request, input_payload, None, None))
