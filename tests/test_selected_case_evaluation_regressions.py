from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from test_selected_case_evaluation import _adapter, _evidence, _FailingAdapter, _prepared_request, _safety_for, _skill

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import (
    execute_selected_case,
    load_selected_case,
)
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence

REVISION = "1" * 40


def test_deterministic_only_case_accepts_empty_satisfied_assertion_ids(tmp_path: Path) -> None:
    """Allow no semantic evidence for a deterministic-only case."""
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
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert definition.semantic_signal_ids == ()
    assert receipt.status == "pass"


def test_missing_adapter_or_semantic_evidence_blocks_without_execution_claim(tmp_path: Path) -> None:
    """Block when the provider adapter or semantic evidence is absent."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)

    receipt = asyncio.run(
        execute_selected_case(
            definition, request, SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)), None, None
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "provider_adapter_required"
    assert receipt.case_results[0].blocker.evidence_refs == ()
    assert receipt.case_results[0].observation_sha256 is None


def test_provider_failure_details_are_preserved_in_blocked_receipt(tmp_path: Path) -> None:
    """Preserve provider failure details in the blocked evaluation receipt."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _FailingAdapter(request),
            _evidence(definition, request, "unused"),
        )
    )
    blocker = receipt.case_results[0].blocker
    assert blocker is not None
    assert blocker.code == "rate_limited"
    assert "retryable=true" in blocker.message
    assert blocker.evidence_refs == ("provider/rate-limit.json",)


def test_output_or_identity_mismatch_blocks_instead_of_fabricating_pass(tmp_path: Path) -> None:
    """Block output identity mismatches instead of fabricating a pass."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "A reviewed answer."
    evidence = _evidence(definition, request, "different output")

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            evidence,
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_identity_mismatch"


def test_assertion_contract_mismatch_blocks_claimed_semantic_pass(tmp_path: Path) -> None:
    """Block semantic evidence bound to a different assertion contract."""
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
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            SelectedCaseJudgeEvidence.model_validate(evidence_payload),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_identity_mismatch"


def test_judge_evidence_round_trips_through_public_schema(tmp_path: Path) -> None:
    """Round-trip valid judge evidence through the public schema registry."""
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
    """Reject credential-shaped evidence refs at model and schema boundaries."""
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


@pytest.mark.parametrize(
    "evidence_ref",
    [
        "/".join(("evidence", "home", "user", "result.json")),
        "/".join(("evidence", "$" + "HOME", "result.json")),
        "evidence/secret=value.json",
    ],
)
def test_judge_evidence_schema_matches_complete_public_reference_screening(tmp_path: Path, evidence_ref: str) -> None:
    """Keep schema screening aligned with complete public reference checks."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload["evidence_refs"] = [evidence_ref]
    with pytest.raises(ValueError):
        SelectedCaseJudgeEvidence.model_validate(payload)
    assert list(Draft202012Validator(SchemaRegistry().load("selected-case-judge-evidence.v1")).iter_errors(payload))


@pytest.mark.parametrize("field", ["evidence_refs", "satisfied_assertion_ids"])
def test_judge_evidence_schema_rejects_duplicate_array_items(tmp_path: Path, field: str) -> None:
    """Reject duplicate judge evidence arrays in the public schema."""
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
    """Block request identity mismatches before provider execution."""
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
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, mismatched)),
            _adapter(mismatched, "reviewed"),
            _evidence(definition, request, "reviewed"),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mismatch"


def test_provider_input_must_match_the_selected_case_prompt(tmp_path: Path) -> None:
    """Require provider input to match the selected-case prompt."""
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
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mismatch"


def test_provider_input_rejects_fields_beyond_the_selected_case_prompt(tmp_path: Path) -> None:
    """Reject provider input fields beyond the selected-case prompt."""
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
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mismatch"


def test_forbidden_command_in_private_output_fails(tmp_path: Path) -> None:
    """Fail a case when private output contains a forbidden command."""
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
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert receipt.status == "fail"
    assert receipt.case_results[0].forbidden_commands_observed == ("rm -rf",)


def test_partial_semantic_judgment_is_a_failed_case(tmp_path: Path) -> None:
    """Fail a case when semantic judgment omits required signals."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "reviewed"
    evidence = _evidence(definition, request, output).model_copy(update={"satisfied_assertion_ids": ()})

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            evidence,
        )
    )

    assert receipt.status == "fail"
    assert set(receipt.case_results[0].missing_signals) == set(definition.semantic_signal_ids)


def test_judge_result_digest_changes_receipt_identity(tmp_path: Path) -> None:
    """Bind receipt identity to the external judge result digest."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "behavior"
    first = _evidence(definition, request, output)
    second = first.model_copy(
        update={
            "judge_result_sha256": "d" * 64,
            "evidence_refs": ("evidence/assertion-review.json", f"judge-results/{'d' * 64}"),
        }
    )

    receipts = [
        asyncio.run(
            execute_selected_case(
                definition,
                request,
                SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
                _adapter(request, output),
                evidence,
            )
        )
        for evidence in (first, second)
    ]

    assert receipts[0].receipt_id != receipts[1].receipt_id
    assert receipts[0].case_results[0].evidence_refs != receipts[1].case_results[0].evidence_refs


def test_forged_judge_evidence_is_revalidated_at_execution(tmp_path: Path) -> None:
    """Revalidate forged judge evidence at the execution boundary."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "behavior"
    forged = _evidence(definition, request, output).model_copy(update={"evidence_refs": ("evidence/ghp_secret.json",)})

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            forged,
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "invalid_judge_evidence"


@pytest.mark.parametrize("field", ["credentials_included", "raw_output_included", "mutation_performed"])
def test_judge_false_only_claims_require_json_booleans(tmp_path: Path, field: str) -> None:
    """Require JSON booleans for judge-owned false-only claims."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload[field] = 0
    with pytest.raises(ValueError, match="JSON booleans"):
        SelectedCaseJudgeEvidence.model_validate(payload)


@pytest.mark.parametrize("field", ["output_sha256", "assertion_contract_sha256", "judge_result_sha256"])
def test_judge_digests_reject_padding(tmp_path: Path, field: str) -> None:
    """Reject padded judge digests before model normalization."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload[field] = f" {payload[field]} "
    with pytest.raises(ValueError, match="normalized"):
        SelectedCaseJudgeEvidence.model_validate(payload)
