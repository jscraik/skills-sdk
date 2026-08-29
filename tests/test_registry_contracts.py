from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.receipts import parse_receipt
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.registry import (
    RegistryIdentity,
    RegistryPreparationBlocker,
    RegistryPreparationReceipt,
    RegistryPreparationRequest,
    RegistryPreparationWarning,
)


def _identity_payload() -> dict[str, object]:
    return {
        "schema_version": "registry-identity/v1",
        "registry_id": "private-registry",
        "registry_kind": "private",
        "namespace": "example-team",
    }


def _prepared_payload() -> dict[str, object]:
    return {
        "schema_version": "registry-preparation/v1",
        "receipt_id": "registry-preparation-1234567890abcdef",
        "candidate": {
            "schema_version": "package-candidate/v1",
            "package_id": "synthetic-skill",
            "source_revision": "1" * 40,
            "content_sha256": "a" * 64,
        },
        "lane": "distribution",
        "registry": _identity_payload(),
        "package_name": "synthetic-skill",
        "version": "0.1.0",
        "input_receipt_id": "package-receipt-1234",
        "package_digest": "b" * 64,
        "manifest_digest": "b" * 64,
        "hardening_receipt_sha256": "c" * 64,
        "status": "prepared",
        "evidence": ["evidence/registry-preparation.json"],
        "warnings": [],
        "mutation_performed": False,
        "publication_performed": False,
    }


def _request_payload() -> dict[str, object]:
    return {
        "schema_version": "registry-preparation-request/v1",
        "registry": _identity_payload(),
        "package_name": "synthetic-skill",
        "version": "0.1.0",
        "evidence": ["evidence/registry-preparation.json"],
    }


def test_registry_identity_is_registered_and_secret_free() -> None:
    identity = RegistryIdentity.model_validate(_identity_payload())
    SchemaRegistry().validate("registry-identity.v1", identity.model_dump(mode="json"))


def test_registry_request_is_registered_and_rejects_duplicate_evidence() -> None:
    payload = _request_payload()
    request = RegistryPreparationRequest.model_validate(payload)
    SchemaRegistry().validate("registry-preparation-request.v1", request.model_dump(mode="json"))
    schema = SchemaRegistry().load("registry-preparation-request.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []

    payload["evidence"] = ["evidence/result.json", "evidence/result.json"]
    with pytest.raises(ValidationError, match="evidence paths must be unique"):
        RegistryPreparationRequest.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("registry-preparation-request.v1", payload)


@pytest.mark.parametrize("delimiter", ["=", "@", "%", "#", "$"])
def test_registry_request_rejects_credential_shaped_evidence_in_all_lanes(delimiter: str) -> None:
    payload = _request_payload()
    payload["evidence"] = [f"token{delimiter}sk-live-secret"]
    with pytest.raises(ValidationError, match="credential-shaped"):
        RegistryPreparationRequest.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("registry-preparation-request.v1", payload)
    schema = SchemaRegistry().load("registry-preparation-request.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize(
    "value",
    [
        "evidence/whiskey-policy.json",
        "evidence/bearish-team.json",
        "evidence/mask-live-secret.json",
    ],
)
def test_registry_request_accepts_noncredential_substrings(value: str) -> None:
    payload = _request_payload()
    payload["evidence"] = [value]
    RegistryPreparationRequest.model_validate(payload)
    SchemaRegistry().validate("registry-preparation-request.v1", payload)
    schema = SchemaRegistry().load("registry-preparation-request.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_registry_blocker_rejects_nonportable_evidence_refs_in_model_and_schema() -> None:
    payload = _prepared_payload()
    blocker = {
        "code": "hardening_blocked",
        "message": "hardening blocked",
        "evidence_refs": ["sensor:policy"],
        "source_evidence_sha256": [],
    }
    with pytest.raises(ValidationError, match="path must be relative"):
        RegistryPreparationBlocker.model_validate(blocker)

    payload.update(
        {
            "status": "blocked",
            "package_digest": None,
            "manifest_digest": None,
            "hardening_receipt_sha256": None,
            "blocker": blocker,
            "blockers": [blocker],
        }
    )
    schema = SchemaRegistry().load("registry-preparation.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("registry-preparation.v1", payload)


def test_registry_blocker_rejects_duplicate_evidence_refs_in_model_and_schema() -> None:
    duplicate_refs = ["evidence/result.json", "evidence/result.json"]
    blocker = {
        "code": "hardening_blocked",
        "message": "hardening blocked",
        "evidence_refs": duplicate_refs,
        "source_evidence_sha256": [],
    }
    with pytest.raises(ValidationError, match="evidence references must be unique"):
        RegistryPreparationBlocker.model_validate(blocker)

    payload = _prepared_payload()
    payload.update(
        {
            "status": "blocked",
            "package_digest": None,
            "manifest_digest": None,
            "hardening_receipt_sha256": None,
            "blocker": blocker,
            "blockers": [blocker],
        }
    )
    schema = SchemaRegistry().load("registry-preparation.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("registry-preparation.v1", payload)


def test_public_registry_evidence_fields_reject_credential_shapes_in_all_lanes() -> None:
    with pytest.raises(ValidationError, match="credential-shaped"):
        RegistryPreparationBlocker(
            code="blocked",
            message="blocked",
            evidence_refs=("sk-live-secret",),
        )
    with pytest.raises(ValidationError, match="credential-shaped"):
        RegistryPreparationWarning(
            warning_sha256="a" * 64,
            evidence_refs=("sk-live-secret",),
        )

    payload = _prepared_payload()
    payload["evidence"] = ["sk-live-secret"]
    with pytest.raises(ValidationError, match="credential-shaped"):
        RegistryPreparationReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("registry-preparation.v1", payload)
    schema = SchemaRegistry().load("registry-preparation.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        parse_receipt(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("registry_id", "private.sk-live-secret"),
        ("registry_id", "private-bearer-secret"),
        ("namespace", "team.github_pat_secret"),
        ("namespace", "team-xoxb-secret"),
    ],
)
def test_registry_identity_rejects_embedded_credential_components(field: str, value: str) -> None:
    payload = _identity_payload()
    payload[field] = value
    with pytest.raises(ValidationError, match="credential-shaped"):
        RegistryIdentity.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("registry-identity.v1", payload)
    schema = SchemaRegistry().load("registry-identity.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("registry_id", "whiskey-registry"),
        ("registry_id", "github-pattern"),
        ("namespace", "bearish-team"),
    ],
)
def test_registry_identity_accepts_ordinary_component_boundaries(field: str, value: str) -> None:
    payload = _identity_payload()
    payload[field] = value
    RegistryIdentity.model_validate(payload)
    SchemaRegistry().validate("registry-identity.v1", payload)


@pytest.mark.parametrize("field", ["token", "endpoint", "headers", "credentials"])
def test_registry_identity_rejects_transport_and_secret_fields(field: str) -> None:
    payload = _identity_payload()
    payload[field] = "untrusted"
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("registry-identity.v1", payload)


@pytest.mark.parametrize(
    "version",
    ["01.0.0", "1.0", "v1.0.0", "1.0.0 ", "1.0.0-", "1.0.0-01"],
)
def test_registry_receipt_rejects_noncanonical_versions(version: str) -> None:
    payload = _prepared_payload()
    payload["version"] = version
    with pytest.raises(ValidationError):
        RegistryPreparationReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("registry-preparation.v1", payload)
    schema = SchemaRegistry().load("registry-preparation.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_registry_receipt_accepts_semantic_version_metadata() -> None:
    payload = _prepared_payload()
    payload["version"] = "1.2.3-rc.1+build.7"
    RegistryPreparationReceipt.model_validate(payload)


def test_prepared_registry_receipt_is_registered_and_generic_parseable() -> None:
    payload = _prepared_payload()
    SchemaRegistry().validate("registry-preparation.v1", payload)
    generic = parse_receipt(payload)
    assert generic.status == "pass"
    assert generic.artifact_status == "prepared"
    assert generic.lane == "distribution"
    assert generic.evidence == ("evidence/registry-preparation.json",)


def test_registry_receipt_rejects_candidate_name_mismatch() -> None:
    payload = _prepared_payload()
    payload["package_name"] = "other-skill"
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("registry-preparation.v1", payload)


def test_registry_receipt_rejects_duplicate_evidence_paths() -> None:
    payload = _prepared_payload()
    payload["evidence"] = ["evidence/result.json", "evidence/result.json"]
    with pytest.raises(ValidationError, match="evidence paths must be unique"):
        RegistryPreparationReceipt.model_validate(payload)
    schema = SchemaRegistry().load("registry-preparation.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_direct_draft_schema_rejects_status_artifact_contradictions() -> None:
    schema = SchemaRegistry().load("registry-preparation.v1")
    prepared = _prepared_payload()
    prepared["package_digest"] = None
    blocked = _prepared_payload()
    blocked.update(
        {
            "status": "blocked",
            "blocker": {"code": "blocked", "message": "blocked", "evidence_refs": []},
        }
    )
    assert list(Draft202012Validator(schema).iter_errors(prepared))
    assert list(Draft202012Validator(schema).iter_errors(blocked))


def test_blocked_receipt_retains_all_typed_blockers_and_evidence() -> None:
    payload = _prepared_payload()
    blockers = [
        {"code": "hardening_blocked", "message": "hardening blocked", "evidence_refs": ["evidence/one.json"]},
        {"code": "provenance_blocked", "message": "provenance blocked", "evidence_refs": ["evidence/two.json"]},
    ]
    payload.update(
        {
            "status": "blocked",
            "package_digest": None,
            "manifest_digest": None,
            "hardening_receipt_sha256": None,
            "blocker": blockers[0],
            "blockers": blockers,
        }
    )

    receipt = RegistryPreparationReceipt.model_validate(payload)
    SchemaRegistry().validate("registry-preparation.v1", payload)
    schema = SchemaRegistry().load("registry-preparation.v1")
    generic = parse_receipt(payload)

    assert list(Draft202012Validator(schema).iter_errors(payload)) == []
    assert receipt.blocker == receipt.blockers[0]
    assert [(item.code, item.evidence_refs) for item in receipt.blockers] == [
        ("hardening_blocked", ("evidence/one.json",)),
        ("provenance_blocked", ("evidence/two.json",)),
    ]
    assert tuple(item["code"] for item in generic.payload["blockers"]) == (
        "hardening_blocked",
        "provenance_blocked",
    )

    payload["blocker"] = blockers[1]
    with pytest.raises(ValidationError, match="primary blocker first"):
        RegistryPreparationReceipt.model_validate(payload)
