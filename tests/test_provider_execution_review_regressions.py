from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk import ProviderExecutionRequest, ProviderExecutionResult, ProviderUsageMetadata
from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.safety import PackageSafetyEvidenceReceipt

FIXTURES = Path(__file__).parent / "fixtures" / "provider-execution"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _not_reviewed_safety_receipt() -> PackageSafetyEvidenceReceipt:
    request = _fixture("request-accepted.json")
    return PackageSafetyEvidenceReceipt.model_validate(
        {
            "schema_version": "package-safety-evidence/v1",
            "receipt_id": request["package_safety_receipt_id"],
            "candidate": request["candidate"],
            "lane": "safety_review",
            "input_receipt_id": "package-receipt-1234",
            "package_digest": "a" * 64,
            "reviewer": {
                "adapter_id": "review/manual",
                "adapter_version_or_digest": "v1",
                "method": "manual_review",
            },
            "status": "not_reviewed",
            "observed_at": "2026-08-29T09:00:00Z",
            "evidence": [],
            "findings": [],
            "blocker": None,
            "blockers": [],
            "mutation_performed": False,
            "rights_decision_performed": False,
            "admission_performed": False,
        }
    )


def test_prepared_request_requires_reviewed_no_issue_safety_evidence() -> None:
    safety = _not_reviewed_safety_receipt()
    safety_payload = safety.model_dump(mode="json")
    request_payload = _fixture("request-accepted.json")
    request_payload["package_safety_receipt_sha256"] = canonical_json_sha256(safety_payload)
    request = ProviderExecutionRequest.model_validate(request_payload)

    with pytest.raises(ValueError, match="reviewed_no_issue"):
        request.validate_against_package_safety_evidence(safety)
    with pytest.raises(ContractError, match="package safety evidence binding"):
        SchemaRegistry().validate_provider_execution_request_against_safety_evidence(request_payload, safety_payload)


def test_result_cannot_start_before_bound_request_preparation() -> None:
    request_payload = _fixture("request-accepted.json")
    request_payload["prepared_at"] = "2026-08-29T14:02:00Z"
    request = ProviderExecutionRequest.model_validate(request_payload)
    result_payload = _fixture("result-accepted.json")
    result_payload["request_sha256"] = canonical_json_sha256(request.model_dump(mode="json"))
    result = ProviderExecutionResult.model_validate(result_payload)

    with pytest.raises(ValueError, match="cannot start before"):
        result.validate_against_request(request)
    with pytest.raises(ContractError, match="provider request binding"):
        SchemaRegistry().validate_provider_execution_result_against_request(result_payload, request_payload)


@pytest.mark.filterwarnings("error")
def test_forged_top_level_result_model_fails_without_serializer_warning() -> None:
    result = ProviderExecutionResult.model_validate(_fixture("result-accepted.json"))
    forged_usage = ProviderUsageMetadata.model_construct(
        unit_kind="tokens", input_units="3", output_units=2, total_units=5
    )

    with pytest.raises(ValidationError):
        ProviderExecutionResult.model_validate(result.model_copy(update={"usage": forged_usage}))


@pytest.mark.filterwarnings("error")
@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "usage",
            {"unit_kind": "tokens", "input_units": 3, "output_units": 2, "total_units": 5},
        ),
        ("started_at", "2026-08-29T14:01:00Z"),
    ],
)
def test_top_level_result_revalidation_accepts_valid_json_form_updates(field: str, value: object) -> None:
    result = ProviderExecutionResult.model_validate(_fixture("result-accepted.json"))

    revalidated = ProviderExecutionResult.model_validate(result.model_copy(update={field: value}))

    assert revalidated == result


def test_published_schemas_name_cross_envelope_semantic_requirements() -> None:
    registry = SchemaRegistry()
    request_requirements = registry.load("provider-execution-request.v1")["x-skills-sdk-semantic-validator"][
        "external_inputs_required_for"
    ]
    result_requirements = registry.load("provider-execution-result.v1")["x-skills-sdk-semantic-validator"][
        "external_inputs_required_for"
    ]

    assert "prepared requests require a reviewed_no_issue supplied safety receipt" in request_requirements
    assert "result start time cannot precede the supplied request preparation time" in result_requirements
