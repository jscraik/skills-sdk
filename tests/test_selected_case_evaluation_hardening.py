"""Regression coverage for selected-case evidence boundary hardening."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from test_selected_case_evaluation import REVISION, _adapter, _evidence, _prepared_request, _safety_for, _skill

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.evaluation.selected_case import SuppliedTextProviderAdapter, execute_selected_case, load_selected_case
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence
from skills_sdk.providers import ProviderAdapterFailure


@pytest.mark.parametrize("evidence_ref", ["evidence/eyJabc.def.ghi.json", "evidence/client_secret.json"])
def test_judge_evidence_model_matches_schema_credential_screening(tmp_path: Path, evidence_ref: str) -> None:
    """Keep model and schema credential screening aligned."""
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
    """Return a typed blocker for unserializable forged judge evidence."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "behavior"
    forged = _evidence(definition, request, output).model_copy(update={"evidence_refs": (object(),)})

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
    assert receipt.case_results[0].blocker.evidence_refs == ()


def test_existing_judge_result_ref_is_not_duplicated(tmp_path: Path) -> None:
    """Avoid duplicating an existing judge-result evidence reference."""
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
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            evidence,
        )
    )

    assert receipt.status == "pass"
    assert receipt.case_results[0].evidence_refs.count(judge_result_ref) == 1


@pytest.mark.parametrize("missing_field", ["deterministic_checks", "forbidden_commands"])
def test_selected_case_requires_declared_deterministic_checks(tmp_path: Path, missing_field: str) -> None:
    """Require selected cases to declare deterministic check fields."""
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
    """Accept an explicitly empty forbidden-command declaration."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["deterministic_checks"]["forbidden_commands"] = []
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")

    assert definition.scenario_set.cases[0].forbidden_commands == ()


@pytest.mark.parametrize("field", ["prompt", "forbidden_commands"])
def test_selected_case_rejects_source_text_that_would_be_stripped(tmp_path: Path, field: str) -> None:
    """Do not execute a prompt or command changed by model normalization."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    case = payload["cases"][0]
    if field == "prompt":
        case["prompt"] = f"{case['prompt']}\n"
    else:
        case["deterministic_checks"]["forbidden_commands"] = [" rm -rf "]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="invalid_selected_case"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_provider_output_evidence_survives_selected_case_receipt(tmp_path: Path) -> None:
    """Preserve provider output evidence in the selected-case receipt."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "reviewed behavior"
    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )
    assert "evidence/provider-output.json" in receipt.case_results[0].evidence_refs


@pytest.mark.parametrize("mode_list", [["release", "standard"], ["release", "release"], ["release", []], []])
def test_selected_case_rejects_invalid_declared_modes(tmp_path: Path, mode_list: list[object]) -> None:
    """Reject invalid or empty declared evaluation mode lists."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["eval_modes"] = mode_list
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="selected_case_mode_mismatch"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize("field", ["case_id", "scenario_set_id", "satisfied_assertion_ids"])
def test_judge_identity_fields_reject_padding(tmp_path: Path, field: str) -> None:
    """Reject padding in judge-owned identity fields."""
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
    """Reject private judge identities in both model and schema validation."""
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
    """Reject private or padded semantic requirement identifiers."""
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
    """Return bound blocker evidence without invoking an adapter."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    prepared = _prepared_request(definition, input_payload)
    payload = prepared.model_dump(mode="json")
    payload["status"] = "blocked"
    payload["blocker"] = {"code": "safety_unavailable", "category": "safety", "evidence_refs": ["evidence/safety.json"]}
    blocked = ProviderExecutionRequest.model_validate(payload)

    receipt = asyncio.run(
        execute_selected_case(definition, blocked, SelectedCaseExecutionInput(input_payload, None), None, None)
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "safety_unavailable"
    assert receipt.case_results[0].blocker.evidence_refs == ("evidence/safety.json",)


def test_mismatched_judge_binding_blocks_before_adapter_call(tmp_path: Path) -> None:
    """Block mismatched judge evidence before calling the provider adapter."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    evidence = _evidence(definition, request, "reviewed").model_copy(update={"assertion_contract_sha256": "d" * 64})

    class NeverCallAdapter:
        descriptor = _adapter(request, "reviewed").descriptor

        async def complete(self, request: object, input_payload: object) -> None:
            """Fail if execution reaches the adapter unexpectedly."""
            raise AssertionError("adapter must not be called")

        async def cleanup(self) -> None:
            """Complete the adapter protocol's no-op cleanup."""
            return None

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            NeverCallAdapter(),
            evidence,
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_identity_mismatch"
    assert receipt.case_results[0].blocker.evidence_refs == ()


def test_forged_provider_request_is_rejected_before_blocked_receipt(tmp_path: Path) -> None:
    """Reject a forged provider request before creating a blocked receipt."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    forged_provider = request.provider.model_copy(update={"model_id": "ghp_secret"})
    forged_request = request.model_copy(update={"provider": forged_provider, "status": "blocked"})

    with pytest.raises(ContractError, match="invalid_provider_request"):
        asyncio.run(
            execute_selected_case(
                definition,
                forged_request,
                SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
                None,
                None,
            )
        )


@pytest.mark.parametrize("field", ["case_id", "scenario_set_id", "satisfied_assertion_ids"])
@pytest.mark.parametrize("padding", [" ", "\n", "\r\n"])
def test_judge_identity_normalization_matches_schema(tmp_path: Path, field: str, padding: str) -> None:
    """Keep judge identity normalization aligned with the public schema."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload[field] = (
        [f"preserve_behavior{padding}"] if field == "satisfied_assertion_ids" else f"{payload[field]}{padding}"
    )

    with pytest.raises(ValueError, match="normalized"):
        SelectedCaseJudgeEvidence.model_validate(payload)
    schema = SchemaRegistry().load("selected-case-judge-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_judge_candidate_id_screening_matches_schema(tmp_path: Path) -> None:
    """Keep candidate identity screening aligned with the public schema."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload["candidate"]["package_id"] = "ghp_secret"

    with pytest.raises(ValueError, match="credential-shaped"):
        SelectedCaseJudgeEvidence.model_validate(payload)
    schema = SchemaRegistry().load("selected-case-judge-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize("field,value", [("source_revision", "not-a-revision"), ("content_sha256", "d" * 63)])
def test_forged_nested_judge_candidate_is_revalidated(tmp_path: Path, field: str, value: str) -> None:
    """Revalidate forged nested candidate fields in judge evidence."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    evidence = _evidence(definition, request, "reviewed")
    forged_candidate = evidence.candidate.model_copy(update={field: value})

    with pytest.raises(ValueError):
        SelectedCaseJudgeEvidence.model_validate(
            evidence.model_copy(update={"candidate": forged_candidate}).model_dump(mode="json")
        )


def test_padded_judge_candidate_revision_is_rejected(tmp_path: Path) -> None:
    """Reject a padded candidate revision in judge evidence."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload["candidate"]["source_revision"] += " "

    with pytest.raises(ValueError, match="normalized"):
        SelectedCaseJudgeEvidence.model_validate(payload)
    schema = SchemaRegistry().load("selected-case-judge-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_private_provider_evidence_ref_returns_blocked_receipt(tmp_path: Path) -> None:
    """Block private provider evidence references without exposing them."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    adapter = _adapter(request, "reviewed")
    adapter = adapter.__class__(adapter.descriptor, adapter.text, ("evidence/client_secret.json",))

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            adapter,
            _evidence(definition, request, "reviewed"),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "private_provider_evidence_ref"
    assert receipt.case_results[0].blocker.evidence_refs == ()
    assert "client_secret" not in receipt.model_dump_json()


def test_supplied_text_adapter_rejects_stream_mode(tmp_path: Path) -> None:
    """Reject a stream descriptor at construction, before provider dispatch."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    adapter = _adapter(request, "reviewed")
    descriptor = adapter.descriptor.model_copy(update={"mode": "stream"})

    with pytest.raises(ContractError, match="unsupported_provider_mode"):
        SuppliedTextProviderAdapter(descriptor, adapter.text, adapter.evidence_refs)


def test_private_provider_failure_code_is_not_published(tmp_path: Path) -> None:
    """Keep credential-shaped adapter failure codes out of public receipts."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)

    class FailingAdapter:
        descriptor = _adapter(request, "reviewed").descriptor

        async def complete(self, request: object, input_payload: object) -> None:
            """Raise an adapter failure carrying a private code."""
            raise ProviderAdapterFailure(code="client_secret", category="provider", retryable=False, evidence_refs=())

        async def cleanup(self) -> None:
            """Complete the adapter protocol's no-op cleanup."""
            return None

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            FailingAdapter(),
            _evidence(definition, request, "reviewed"),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "invalid_provider_failure"
    assert "client_secret" not in receipt.model_dump_json()
