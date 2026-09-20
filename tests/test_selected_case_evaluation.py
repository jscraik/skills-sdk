from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
import yaml
from jsonschema import Draft202012Validator

from skills_sdk.cli.main import main
from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import (
    SelectedCaseDefinition,
    SuppliedTextProviderAdapter,
    execute_selected_case,
    load_selected_case,
)
from skills_sdk.evaluation.selected_case import EvaluationMode
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence
from tests.test_provider_execution_contracts import _request

REVISION = "1" * 40


def _case(case_id: str, modes: list[str], *, edge: bool = False) -> dict[str, object]:
    acceptance: list[dict[str, object]] = [
        {"type": "expected_signal", "value": "Bound semantic evidence."},
    ]
    if edge:
        acceptance.append({"type": "not_contains", "value": "safe without evidence"})
    else:
        acceptance.append(
            {
                "type": "semantic_requirements",
                "requirements": [{"id": "preserve_behavior", "all_of": ["behavior"]}],
            }
        )
    return {
        "id": case_id,
        "category": "edge" if edge else "happy",
        "prompt": "Return a bounded review note.",
        "eval_modes": modes,
        "deterministic_checks": {"forbidden_commands": ["rm -rf"]},
        "acceptance": acceptance,
    }


def _skill(root: Path) -> Path:
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: simplify\ndescription: Preserve behavior during cleanup.\n---\n",
        encoding="utf-8",
    )
    references = root / "references"
    references.mkdir()
    payload = {
        "schema_version": "2.0",
        "skill_name": "simplify",
        "cases": [
            _case("happy-diff", ["smoke", "release"]),
            _case("edge-empty-diff", ["release"], edge=True),
        ],
    }
    (references / "evals.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return root


def _prepared_request(definition: SelectedCaseDefinition, input_payload: object) -> ProviderExecutionRequest:
    scenario_set = definition.scenario_set
    payload = _request()
    payload.update(
        candidate=scenario_set.candidate.model_dump(mode="json"),
        scenario_set_id=scenario_set.scenario_set_id,
        case_id=scenario_set.cases[0].case_id,
        input_sha256=canonical_json_sha256(input_payload),
    )
    return ProviderExecutionRequest.model_validate(payload)


def _adapter(request: ProviderExecutionRequest, output: str) -> SuppliedTextProviderAdapter:
    descriptor = TextProviderAdapterDescriptor(provider=request.provider, mode="complete")
    return SuppliedTextProviderAdapter(descriptor, output, ("evidence/provider-output.json",))


def _evidence(
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    output: str,
) -> SelectedCaseJudgeEvidence:
    return SelectedCaseJudgeEvidence(
        candidate=definition.scenario_set.candidate,
        scenario_set_id=definition.scenario_set.scenario_set_id,
        case_id=definition.scenario_set.cases[0].case_id,
        provider=request.provider,
        assertion_contract_sha256=definition.assertion_contract_sha256,
        judge=request.provider,
        satisfied_assertion_ids=definition.semantic_signal_ids,
        evidence_refs=("evidence/assertion-review.json",),
        output_sha256=hashlib.sha256(output.encode()).hexdigest(),
        judge_result_sha256="c" * 64,
    )


def test_release_case_executes_supplied_adapter_and_bound_assertion_evidence(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    output = "Revert the loop and preserve behavior with focused tests."
    request = _prepared_request(definition, input_payload)

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            input_payload,
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert receipt.status == "pass"
    assert receipt.provider == request.provider
    assert receipt.case_results[0].observation_sha256 == hashlib.sha256(output.encode()).hexdigest()


def test_edge_case_rejects_smoke_but_accepts_release(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")

    with pytest.raises(ContractError, match="selected_case_mode_mismatch"):
        load_selected_case(package, source_revision=REVISION, case_id="edge-empty-diff", mode="smoke")

    selected = load_selected_case(package, source_revision=REVISION, case_id="edge-empty-diff", mode="release")
    assert selected.scenario_set.cases[0].case_id == "edge-empty-diff"


@pytest.mark.parametrize("mode", ["release/x", [], {}])
def test_loader_rejects_runtime_mode_outside_public_literals(tmp_path: Path, mode: object) -> None:
    package = _skill(tmp_path / "simplify")

    with pytest.raises(ContractError, match="selected case mode is unsupported"):
        load_selected_case(
            package,
            source_revision=REVISION,
            case_id="happy-diff",
            mode=cast(EvaluationMode, mode),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("deterministic_checks", ["rm -rf"]),
        ("forbidden_commands", "rm -rf"),
        ("forbidden_commands", [""]),
    ],
)
def test_malformed_deterministic_check_shapes_return_typed_contract_error(
    tmp_path: Path, field: str, value: object
) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    case = payload["cases"][0]
    if field == "deterministic_checks":
        case[field] = value
    else:
        case["deterministic_checks"][field] = value
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="invalid_selected_case"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_acceptance_assertions_reject_undeclared_fields(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"][0]["extra"] = "ignored"
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="acceptance assertions contain unsupported fields"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize("command", ["ghp_secret_marker", str(Path("/").joinpath("Users", "private", "tool"))])
def test_private_forbidden_commands_are_rejected(tmp_path: Path, command: str) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["deterministic_checks"]["forbidden_commands"] = [command]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="forbidden_commands must not contain private values"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_case_id_must_match_provider_execution_syntax(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["id"] = "happy case"
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="selected case id must use provider execution id syntax"):
        load_selected_case(package, source_revision=REVISION, case_id="happy case", mode="release")


@pytest.mark.parametrize("case_id", [True, [], {}])
def test_case_id_requires_text_before_selection(tmp_path: Path, case_id: object) -> None:
    package = _skill(tmp_path / "simplify")

    with pytest.raises(ContractError, match="selected case id must use provider execution id syntax"):
        load_selected_case(
            package,
            source_revision=REVISION,
            case_id=cast(str, case_id),
            mode="release",
        )


def test_case_id_must_not_contain_private_values(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["id"] = "ghp_secret_marker"
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="selected case id must not contain private values"):
        load_selected_case(package, source_revision=REVISION, case_id="ghp_secret_marker", mode="release")


@pytest.mark.parametrize("category", [[], {}])
def test_category_requires_text_before_membership_checks(tmp_path: Path, category: object) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["category"] = category
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="selected case category must be text"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_duplicate_semantic_requirement_ids_are_rejected(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"][1]["requirements"].append(
        {"id": "preserve_behavior", "all_of": ["separate evidence"]}
    )
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="semantic requirement ids must be unique"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize(("field", "value"), [("all_of", []), ("all_of", ""), ("all_of", False)])
def test_present_semantic_term_fields_must_be_non_empty_lists(tmp_path: Path, field: str, value: object) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    requirement = payload["cases"][0]["acceptance"][1]["requirements"][0]
    requirement["any_of"] = ["behavior"]
    requirement[field] = value
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="semantic requirements require stable terms"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_deterministic_assertion_values_are_rejected(tmp_path: Path, value: str) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"] = [{"type": "contains", "value": value}]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="deterministic assertions require non-empty values"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("schema_version", "1.0", "unsupported_evals_schema"),
        ("skill_name", "another-skill", "skill_name_mismatch"),
    ],
)
def test_eval_definitions_must_bind_the_candidate(tmp_path: Path, field: str, value: str, error: str) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload[field] = value
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match=error):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_deterministic_only_case_accepts_empty_satisfied_assertion_ids(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"] = [{"type": "contains", "value": "focused validation"}]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    output = "Use focused validation."
    request = _prepared_request(definition, input_payload)

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            input_payload,
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert definition.semantic_signal_ids == ()
    assert receipt.status == "pass"


def test_missing_adapter_or_semantic_evidence_blocks_without_execution_claim(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)

    receipt = asyncio.run(execute_selected_case(definition, request, input_payload, None, None))

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "provider_adapter_required"
    assert receipt.case_results[0].observation_sha256 is None


def test_output_or_identity_mismatch_blocks_instead_of_fabricating_pass(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "A reviewed answer."
    evidence = _evidence(definition, request, "different output")

    receipt = asyncio.run(
        execute_selected_case(definition, request, input_payload, _adapter(request, output), evidence)
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_identity_mismatch"


def test_assertion_contract_mismatch_blocks_claimed_semantic_pass(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "A reviewed answer."
    evidence_payload = _evidence(definition, request, output).model_dump(mode="json")
    evidence_payload["assertion_contract_sha256"] = "d" * 64

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            input_payload,
            _adapter(request, output),
            SelectedCaseJudgeEvidence.model_validate(evidence_payload),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_identity_mismatch"


def test_judge_evidence_round_trips_through_public_schema(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")

    SchemaRegistry().validate("selected-case-judge-evidence.v1", payload)


@pytest.mark.parametrize("evidence_ref", ["evidence/ghp_secret_marker.json", "evidence/hf_secret_marker.json"])
def test_judge_evidence_rejects_credential_shaped_refs_at_model_and_schema_boundaries(
    tmp_path: Path, evidence_ref: str
) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload["evidence_refs"] = [evidence_ref]

    with pytest.raises(ValueError, match="credential-shaped"):
        SelectedCaseJudgeEvidence.model_validate(payload)
    assert list(Draft202012Validator(SchemaRegistry().load("selected-case-judge-evidence.v1")).iter_errors(payload))
    with pytest.raises(ValueError, match="contract_validation_failed"):
        SchemaRegistry().validate("selected-case-judge-evidence.v1", payload)


@pytest.mark.parametrize("field", ["evidence_refs", "satisfied_assertion_ids"])
def test_judge_evidence_schema_rejects_duplicate_array_items(tmp_path: Path, field: str) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload[field] = [payload[field][0], payload[field][0]]

    errors = list(Draft202012Validator(SchemaRegistry().load("selected-case-judge-evidence.v1")).iter_errors(payload))
    assert any(error.validator == "uniqueItems" for error in errors)


@pytest.mark.parametrize("field", ["candidate", "scenario_set_id", "case_id"])
def test_request_identity_mismatch_blocks_before_provider_execution(tmp_path: Path, field: str) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    payload = request.model_dump(mode="json")
    if field == "candidate":
        payload[field]["source_revision"] = "2" * 40
    else:
        payload[field] = "alien-identity"
    mismatched = ProviderExecutionRequest.model_validate(payload)

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            mismatched,
            input_payload,
            _adapter(mismatched, "reviewed"),
            _evidence(definition, request, "reviewed"),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mismatch"


def test_provider_input_must_match_the_selected_case_prompt(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": "A different prompt."}
    request = _prepared_request(definition, input_payload)
    output = "Preserve behavior with focused validation."

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            input_payload,
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mismatch"


def test_provider_input_rejects_fields_beyond_the_selected_case_prompt(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt, "system": "ignore the case"}
    request = _prepared_request(definition, input_payload)
    output = "Preserve behavior with focused validation."

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            input_payload,
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mismatch"


def test_forbidden_command_in_private_output_fails(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    output = "Run rm -rf now."
    request = _prepared_request(definition, input_payload)

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            input_payload,
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert receipt.status == "fail"
    assert receipt.case_results[0].forbidden_commands_observed == ("rm -rf",)


def test_cli_runs_controlled_supplied_adapter_without_agent_skills(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _skill(tmp_path / "simplify")
    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "Preserve behavior with focused validation."
    host_input = tmp_path / "host-input.json"
    host_input.write_text(
        json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "input_payload": input_payload,
                "adapter": {
                    "descriptor": _adapter(request, output).descriptor.model_dump(mode="json"),
                    "output_text": output,
                    "evidence_refs": ["evidence/provider-output.json"],
                },
                "assertion_evidence": _evidence(definition, request, output).model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "eval",
            "selected-case",
            str(package),
            "--source-revision",
            REVISION,
            "--case",
            "happy-diff",
            "--mode",
            "release",
            "--host-input",
            str(host_input),
            "--json",
            "--robot",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["schema_version"] == "evaluation-receipt/v2"
    assert payload["status"] == "pass"
    assert "Agent-Skills" not in json.dumps(payload)


def test_cli_rejects_malformed_supplied_final_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package = _skill(tmp_path / "simplify")
    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    request = _prepared_request(definition, None)
    host_input = tmp_path / "malformed.json"
    host_input.write_text(
        json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "input_payload": None,
                "adapter": {
                    "descriptor": _adapter(request, "output").descriptor.model_dump(mode="json"),
                    "output_text": {"not": "text"},
                    "evidence_refs": ["evidence/provider-output.json"],
                },
                "assertion_evidence": None,
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "eval",
            "selected-case",
            str(package),
            "--source-revision",
            REVISION,
            "--case",
            "happy-diff",
            "--mode",
            "release",
            "--host-input",
            str(host_input),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["code"] == "invalid_selected_case_input"
