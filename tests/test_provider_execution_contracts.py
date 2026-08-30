from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ValidationError

from skills_sdk import (
    ProviderExecutionBlocker,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderIdentityV2,
    ProviderUsageMetadata,
)
from skills_sdk.core.errors import ContractError
from skills_sdk.core.receipts import parse_receipt
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.package import PackageCandidateIdentity

FIXTURES = Path(__file__).parent / "fixtures" / "provider-execution"


def _candidate() -> dict[str, object]:
    return {
        "schema_version": "package-candidate/v1",
        "package_id": "synthetic-skill",
        "source_revision": "1" * 40,
        "content_sha256": "a" * 64,
    }


def _provider() -> dict[str, object]:
    return {
        "schema_version": "provider-identity/v2",
        "provider_id": "synthetic-provider",
        "provider_kind": "external",
        "model_id": "provider/model-v1",
        "version_or_digest": "v1",
        "adapter_id": "synthetic-adapter",
        "adapter_version_or_digest": "v1",
    }


def _request(status: str = "prepared") -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "provider-execution-request/v1",
        "request_id": "request-1234",
        "candidate": _candidate(),
        "scenario_set_id": "scenario-set-1",
        "case_id": "case-1",
        "provider": _provider(),
        "declared_capability": "response_generation",
        "input_sha256": "b" * 64,
        "idempotency_key_sha256": "c" * 64,
        "package_safety_receipt_id": "package-safety-review-1234",
        "package_safety_receipt_sha256": "d" * 64,
        "prepared_at": "2026-08-29T14:00:00Z",
        "status": status,
        "blocker": None,
        "evidence_refs": ["evidence/request.json"],
        "provider_execution_performed": False,
        "credentials_included": False,
        "raw_payloads_included": False,
        "cost_claimed": False,
    }
    if status == "blocked":
        payload["blocker"] = {
            "code": "safety_review_required",
            "category": "safety",
            "evidence_refs": ["evidence/safety.json"],
        }
    return payload


def _result(status: str = "completed") -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "provider-execution-result/v1",
        "result_id": "result-1234",
        "request_id": "request-1234",
        "request_sha256": "e" * 64,
        "idempotency_key_sha256": "c" * 64,
        "candidate": _candidate(),
        "scenario_set_id": "scenario-set-1",
        "case_id": "case-1",
        "provider": _provider(),
        "status": status,
        "started_at": "2026-08-29T14:01:00Z",
        "finished_at": "2026-08-29T14:01:02Z",
        "output_sha256": "f" * 64,
        "usage": {"unit_kind": "tokens", "input_units": 3, "output_units": 2, "total_units": 5},
        "evidence_refs": ["evidence/result.json"],
        "blocker": None,
        "error": None,
        "replay_of_result_id": None,
        "replay_of_result_sha256": None,
        "sdk_execution_performed": False,
        "credentials_retained": False,
        "raw_payloads_retained": False,
        "cost_claimed": False,
    }
    if status == "failed":
        payload["output_sha256"] = None
        payload["error"] = {
            "code": "provider_rejected",
            "category": "provider",
            "retryable": False,
            "evidence_refs": ["evidence/error.json"],
        }
    elif status == "blocked":
        payload["output_sha256"] = None
        payload["usage"] = None
        payload["blocker"] = {
            "code": "policy_blocked",
            "category": "policy",
            "evidence_refs": ["evidence/policy.json"],
        }
    elif status == "indeterminate":
        payload["output_sha256"] = None
        payload["usage"] = None
        payload["error"] = {
            "code": "transport_indeterminate",
            "category": "transport",
            "retryable": True,
            "evidence_refs": ["evidence/transport.json"],
        }
    return payload


def _assert_model_draft_and_registry_reject(payload: dict[str, object]) -> None:
    schema_version = str(payload["schema_version"])
    model = ProviderExecutionRequest if schema_version.endswith("request/v1") else ProviderExecutionResult
    schema_name = schema_version.replace("/", ".")

    with pytest.raises(ValidationError):
        model.model_validate(payload)
    schema = SchemaRegistry().load(schema_name)
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match=r"contract_validation_failed|invalid_json_value"):
        SchemaRegistry().validate(schema_name, payload)


@pytest.mark.parametrize(
    ("schema_name", "payload"),
    [
        ("provider-execution-request.v1", _request()),
        ("provider-execution-request.v1", _request("blocked")),
        ("provider-execution-result.v1", _result()),
        ("provider-execution-result.v1", _result("failed")),
        ("provider-execution-result.v1", _result("blocked")),
        ("provider-execution-result.v1", _result("indeterminate")),
    ],
)
def test_provider_execution_states_validate_in_model_registry_and_draft(
    schema_name: str, payload: dict[str, object]
) -> None:
    model = ProviderExecutionRequest if "request" in schema_name else ProviderExecutionResult
    assert model.model_validate(payload).status == payload["status"]
    SchemaRegistry().validate(schema_name, payload)
    schema = SchemaRegistry().load(schema_name)
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload)) == []


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({**_request(), "status": "blocked", "blocker": None}, "requires a blocker"),
        ({**_request(), "blocker": {"code": "blocked", "category": "policy", "evidence_refs": []}}, "cannot contain"),
        ({**_result(), "output_sha256": None}, "requires output evidence"),
        (
            {
                **_result("blocked"),
                "usage": {"unit_kind": "tokens", "input_units": 1, "output_units": 0, "total_units": 1},
            },
            "requires only a blocker",
        ),
    ],
)
def test_status_boundaries_fail_closed_in_model_and_draft(payload: dict[str, object], message: str) -> None:
    model = (
        ProviderExecutionRequest
        if payload["schema_version"] == "provider-execution-request/v1"
        else ProviderExecutionResult
    )
    schema_name = str(payload["schema_version"]).replace("/", ".")
    with pytest.raises(ValidationError, match=message):
        model.model_validate(payload)
    schema = SchemaRegistry().load(schema_name)
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_result_timestamps_and_usage_totals_fail_semantic_validation() -> None:
    payload = _result()
    payload["finished_at"] = "2026-08-29T13:59:00Z"
    usage = payload["usage"]
    assert isinstance(usage, dict)
    usage["total_units"] = 99

    with pytest.raises(ValidationError):
        ProviderExecutionResult.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("provider-execution-result.v1", payload)


@pytest.mark.parametrize("missing_field", ["replay_of_result_id", "replay_of_result_sha256"])
def test_replay_identity_and_digest_are_required_together_by_model_and_draft(missing_field: str) -> None:
    payload = _result()
    payload["replay_of_result_id"] = "result-prior"
    payload["replay_of_result_sha256"] = "9" * 64
    payload.pop(missing_field)

    with pytest.raises(ValidationError, match="supplied together"):
        ProviderExecutionResult.model_validate(payload)
    schema = SchemaRegistry().load("provider-execution-result.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_replay_identity_and_digest_pair_is_accepted() -> None:
    payload = _result()
    payload["replay_of_result_id"] = "result-prior"
    payload["replay_of_result_sha256"] = "9" * 64

    assert ProviderExecutionResult.model_validate(payload).replay_of_result_id == "result-prior"
    SchemaRegistry().validate("provider-execution-result.v1", payload)
    schema = SchemaRegistry().load("provider-execution-result.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


@pytest.mark.parametrize("retained_null", ["replay_of_result_id", "replay_of_result_sha256"])
def test_explicit_null_replay_field_matches_omitted_counterpart(retained_null: str) -> None:
    payload = _result()
    omitted = {"replay_of_result_id", "replay_of_result_sha256"} - {retained_null}
    payload.pop(omitted.pop())

    assert ProviderExecutionResult.model_validate(payload).replay_of_result_id is None
    SchemaRegistry().validate("provider-execution-result.v1", payload)
    schema = SchemaRegistry().load("provider-execution-result.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_replay_cannot_reference_the_current_result() -> None:
    payload = _result()
    payload["replay_of_result_id"] = payload["result_id"]
    payload["replay_of_result_sha256"] = "9" * 64

    with pytest.raises(ValidationError, match="cannot replay itself"):
        ProviderExecutionResult.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("provider-execution-result.v1", payload)


@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (_request, "request_id"),
        (_request, "package_safety_receipt_id"),
        (_result, "result_id"),
        (_result, "request_id"),
    ],
)
def test_public_execution_ids_reject_credential_shapes_at_all_boundaries(
    factory: Callable[[], dict[str, object]], field: str
) -> None:
    payload = factory()
    payload[field] = "ghp_secret_marker"
    model = (
        ProviderExecutionRequest
        if payload["schema_version"] == "provider-execution-request/v1"
        else ProviderExecutionResult
    )
    schema_name = str(payload["schema_version"]).replace("/", ".")

    with pytest.raises(ValidationError, match="credential-shaped"):
        model.model_validate(payload)
    schema = SchemaRegistry().load(schema_name)
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate(schema_name, payload)


@pytest.mark.parametrize("credential_shape", ["AIzaSyntheticMarker", "hf_synthetic_marker"])
@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (_request, "request_id"),
        (_request, "package_safety_receipt_id"),
        (_result, "result_id"),
        (_result, "request_id"),
    ],
)
def test_execution_identity_rejects_extended_credential_prefixes_at_all_boundaries(
    credential_shape: str,
    factory: Callable[[], dict[str, object]],
    field: str,
) -> None:
    payload = factory()
    payload[field] = credential_shape
    _assert_model_draft_and_registry_reject(payload)


@pytest.mark.parametrize("factory", [_request, _result])
@pytest.mark.parametrize("credential_shape", ["ghp_secret_marker", "hf_secret_marker"])
def test_candidate_package_id_rejects_credential_shapes_at_all_boundaries(
    factory: Callable[[], dict[str, object]], credential_shape: str
) -> None:
    payload = factory()
    candidate = payload["candidate"]
    assert isinstance(candidate, dict)
    candidate["package_id"] = credential_shape

    _assert_model_draft_and_registry_reject(payload)


@pytest.mark.parametrize("factory", [_request, _result])
@pytest.mark.parametrize("accepted_id", ["ghp-safe", "hf-safe"])
def test_candidate_package_id_accepts_noncredential_boundaries(
    factory: Callable[[], dict[str, object]], accepted_id: str
) -> None:
    payload = factory()
    candidate = payload["candidate"]
    assert isinstance(candidate, dict)
    candidate["package_id"] = accepted_id

    model = (
        ProviderExecutionRequest
        if payload["schema_version"] == "provider-execution-request/v1"
        else ProviderExecutionResult
    )
    schema_name = str(payload["schema_version"]).replace("/", ".")
    model.model_validate(payload)
    schema = SchemaRegistry().load(schema_name)
    assert not list(Draft202012Validator(schema).iter_errors(payload))
    SchemaRegistry().validate(schema_name, payload)


@pytest.mark.parametrize(
    "machine_path",
    [
        "evidence/" + "Users/alice/private.json",
        "reports/workspace/project/output.json",
        "records/tmp/provider.json",
        "evidence/C:/" + "Users/alice/provider.json",
    ],
)
@pytest.mark.parametrize("target", ["request", "result", "blocker", "error"])
def test_execution_evidence_rejects_embedded_machine_paths_at_all_boundaries(machine_path: str, target: str) -> None:
    payload = _request() if target in {"request", "blocker"} else _result("failed")
    if target in {"request", "result"}:
        payload["evidence_refs"] = [machine_path]
    elif target == "blocker":
        payload = _request("blocked")
        blocker = payload["blocker"]
        assert isinstance(blocker, dict)
        blocker["evidence_refs"] = [machine_path]
    else:
        error = payload["error"]
        assert isinstance(error, dict)
        error["evidence_refs"] = [machine_path]
    _assert_model_draft_and_registry_reject(payload)


def test_completed_result_requires_evidence_refs_at_all_boundaries() -> None:
    payload = _result()
    payload.pop("evidence_refs")

    _assert_model_draft_and_registry_reject(payload)


@pytest.mark.parametrize("coerced_value", [0, 1, "false", "true"])
@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (_request, "provider_execution_performed"),
        (_request, "credentials_included"),
        (_request, "raw_payloads_included"),
        (_request, "cost_claimed"),
        (_result, "sdk_execution_performed"),
        (_result, "credentials_retained"),
        (_result, "raw_payloads_retained"),
        (_result, "cost_claimed"),
    ],
)
def test_false_only_fields_reject_boolean_coercion_at_all_boundaries(
    factory: Callable[[], dict[str, object]], field: str, coerced_value: object
) -> None:
    payload = factory()
    payload[field] = coerced_value

    _assert_model_draft_and_registry_reject(payload)


@pytest.mark.parametrize("coerced_value", [0, 1, "false", "true"])
def test_retryable_rejects_boolean_coercion_at_all_boundaries(coerced_value: object) -> None:
    payload = _result("failed")
    error = payload["error"]
    assert isinstance(error, dict)
    error["retryable"] = coerced_value

    _assert_model_draft_and_registry_reject(payload)


@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (_request, "request_id"),
        (_request, "scenario_set_id"),
        (_request, "case_id"),
        (_request, "package_safety_receipt_id"),
        (_request, "input_sha256"),
        (_request, "idempotency_key_sha256"),
        (_request, "package_safety_receipt_sha256"),
        (_result, "result_id"),
        (_result, "request_id"),
        (_result, "scenario_set_id"),
        (_result, "case_id"),
        (_result, "request_sha256"),
        (_result, "idempotency_key_sha256"),
        (_result, "output_sha256"),
    ],
)
def test_opaque_bindings_reject_surrounding_whitespace_at_all_boundaries(
    factory: Callable[[], dict[str, object]], field: str
) -> None:
    payload = factory()
    value = payload[field]
    assert isinstance(value, str)
    payload[field] = f" {value} "

    _assert_model_draft_and_registry_reject(payload)


@pytest.mark.parametrize("field", ["replay_of_result_id", "replay_of_result_sha256"])
def test_replay_bindings_reject_surrounding_whitespace_at_all_boundaries(field: str) -> None:
    payload = _result()
    payload["replay_of_result_id"] = "result-prior"
    payload["replay_of_result_sha256"] = "9" * 64
    value = payload[field]
    assert isinstance(value, str)
    payload[field] = f" {value} "

    _assert_model_draft_and_registry_reject(payload)


@pytest.mark.parametrize("factory", [_request, _result])
@pytest.mark.parametrize("field", ["package_id", "source_revision", "content_sha256"])
def test_candidate_bindings_reject_surrounding_whitespace_at_all_boundaries(
    factory: Callable[[], dict[str, object]], field: str
) -> None:
    payload = factory()
    candidate = payload["candidate"]
    assert isinstance(candidate, dict)
    value = candidate[field]
    assert isinstance(value, str)
    candidate[field] = f" {value} "

    _assert_model_draft_and_registry_reject(payload)


def test_usage_counts_reject_string_coercion_at_all_boundaries() -> None:
    payload = _result()
    usage = payload["usage"]
    assert isinstance(usage, dict)
    usage["input_units"] = "3"

    _assert_model_draft_and_registry_reject(payload)


def test_timestamps_reject_python_datetime_coercion_at_all_boundaries() -> None:
    payload = _request()
    payload["prepared_at"] = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)

    _assert_model_draft_and_registry_reject(payload)


def test_evidence_refs_reject_generator_input_at_all_boundaries() -> None:
    payload = _request()
    payload["evidence_refs"] = (item for item in ["evidence/request.json"])

    _assert_model_draft_and_registry_reject(payload)


def _assert_forged_nested_model_rejected(
    payload: dict[str, object],
    field: str,
    schema_name: str,
    model: type[ProviderExecutionRequest] | type[ProviderExecutionResult],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    nested = payload[field]
    assert isinstance(nested, BaseModel)
    serialized = {**payload, field: dict(nested)}
    schema = SchemaRegistry().load(schema_name)
    assert list(Draft202012Validator(schema).iter_errors(serialized))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate(schema_name, serialized)


def test_forged_candidate_model_is_revalidated() -> None:
    payload = _request()
    payload["candidate"] = PackageCandidateIdentity.model_construct(
        schema_version="package-candidate/v1",
        package_id=" invalid package ",
        source_revision="1" * 40,
        content_sha256="a" * 64,
    )

    _assert_forged_nested_model_rejected(
        payload, "candidate", "provider-execution-request.v1", ProviderExecutionRequest
    )


def test_forged_provider_model_is_revalidated() -> None:
    payload = _request()
    payload["provider"] = ProviderIdentityV2.model_construct(
        schema_version="provider-identity/v2",
        provider_id="invalid provider",
        provider_kind="external",
        model_id="https://provider.example/model",
        version_or_digest="v1",
        adapter_id="synthetic-adapter",
        adapter_version_or_digest="v1",
    )

    _assert_forged_nested_model_rejected(payload, "provider", "provider-execution-request.v1", ProviderExecutionRequest)


def test_forged_usage_model_is_revalidated() -> None:
    payload = _result()
    payload["usage"] = ProviderUsageMetadata.model_construct(
        unit_kind="tokens", input_units="3", output_units=2, total_units=5
    )

    _assert_forged_nested_model_rejected(payload, "usage", "provider-execution-result.v1", ProviderExecutionResult)


def test_forged_blocker_model_is_revalidated() -> None:
    payload = _request("blocked")
    payload["blocker"] = ProviderExecutionBlocker.model_construct(
        code="invalid code", category="policy", evidence_refs=()
    )

    _assert_forged_nested_model_rejected(payload, "blocker", "provider-execution-request.v1", ProviderExecutionRequest)


def test_forged_error_model_is_revalidated() -> None:
    payload = _result("failed")
    payload["error"] = ProviderExecutionError.model_construct(
        code="provider_rejected",
        category="provider",
        retryable="false",
        evidence_refs=("evidence/error.json",),
    )

    _assert_forged_nested_model_rejected(payload, "error", "provider-execution-result.v1", ProviderExecutionResult)


def test_valid_nested_models_remain_supported() -> None:
    request = _request()
    request["candidate"] = PackageCandidateIdentity.model_validate(request["candidate"])
    request["provider"] = ProviderIdentityV2.model_validate(request["provider"])
    assert ProviderExecutionRequest.model_validate(request).status == "prepared"

    result = _result()
    usage = result["usage"]
    assert isinstance(usage, dict)
    result["usage"] = ProviderUsageMetadata.model_validate(usage)
    assert ProviderExecutionResult.model_validate(result).status == "completed"


@pytest.mark.parametrize("extra_field", ["credential", "raw_prompt", "raw_output", "cost"])
def test_raw_secret_and_cost_fields_are_rejected(extra_field: str) -> None:
    payload = _request()
    payload[extra_field] = "not-allowed"
    _assert_model_draft_and_registry_reject(payload)


def test_semantic_validator_metadata_is_contract_specific() -> None:
    request_metadata = SchemaRegistry().load("provider-execution-request.v1")["x-skills-sdk-semantic-validator"]
    result_metadata = SchemaRegistry().load("provider-execution-result.v1")["x-skills-sdk-semantic-validator"]

    assert request_metadata == {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": ["request status and blocker must agree"],
    }
    assert result_metadata == {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": [
            "timestamps must be ordered",
            "usage totals must match their components",
            "a replay result cannot reference itself",
        ],
    }


def test_request_and_result_contracts_are_not_generic_receipts() -> None:
    for payload in (_request(), _result()):
        original = deepcopy(payload)
        with pytest.raises(ContractError, match="unsupported_receipt_family"):
            parse_receipt(payload)
        assert payload == original


def test_provider_execution_requires_provider_identity_v2() -> None:
    payload = _request()
    provider = payload["provider"]
    assert isinstance(provider, dict)
    provider["schema_version"] = "provider-identity/v1"

    with pytest.raises(ValidationError):
        ProviderExecutionRequest.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("provider-execution-request.v1", payload)


@pytest.mark.parametrize(
    ("filename", "schema_name", "model"),
    [
        ("request-accepted.json", "provider-execution-request.v1", ProviderExecutionRequest),
        ("result-accepted.json", "provider-execution-result.v1", ProviderExecutionResult),
    ],
)
def test_provider_execution_fixtures_are_public_contract_examples(
    filename: str,
    schema_name: str,
    model: type[ProviderExecutionRequest] | type[ProviderExecutionResult],
) -> None:
    payload = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
    model.model_validate(payload)
    SchemaRegistry().validate(schema_name, payload)
