from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.receipts import parse_receipt
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.packaging import PackageReceiptV2
from skills_sdk.models.safety import PackageSafetyEvidenceReceipt

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "package-receipts"


def _payload(status: str = "reviewed_no_issue") -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "package-safety-evidence/v1",
        "receipt_id": "package-safety-review-1234",
        "candidate": {
            "schema_version": "package-candidate/v1",
            "package_id": "synthetic-skill",
            "source_revision": "1" * 40,
            "content_sha256": "a" * 64,
        },
        "lane": "safety_review",
        "input_receipt_id": "package-receipt-1234",
        "package_digest": "a" * 64,
        "reviewer": {
            "adapter_id": "review/manual",
            "adapter_version_or_digest": "v1",
            "method": "manual_review",
        },
        "status": status,
        "observed_at": "2026-08-29T09:00:00Z",
        "evidence": [
            {
                "evidence_id": "review-report",
                "kind": "manual_review",
                "ref": "evidence/safety-review.json",
                "sha256": "c" * 64,
            }
        ],
        "findings": [],
        "blocker": None,
        "blockers": [],
        "mutation_performed": False,
        "rights_decision_performed": False,
        "admission_performed": False,
    }
    if status == "not_reviewed":
        payload["evidence"] = []
    elif status == "issue_found":
        payload["findings"] = [
            {
                "code": "unsafe_operation",
                "category": "unsafe_operation",
                "severity": "blocker",
                "message": "declared operation requires review",
                "evidence_ids": ["review-report"],
            }
        ]
        blocker = {
            "code": "issue_found",
            "message": "package safety issue found",
            "evidence_refs": ["evidence/safety-review.json"],
        }
        payload["blocker"] = blocker
        payload["blockers"] = [blocker]
    elif status == "metadata_insufficient":
        payload["evidence"] = []
        blocker = {
            "code": "metadata_insufficient",
            "message": "metadata cannot establish a review result",
            "evidence_refs": [],
        }
        payload["blocker"] = blocker
        payload["blockers"] = [blocker]
    return payload


@pytest.mark.parametrize(
    "status",
    ["not_reviewed", "reviewed_no_issue", "issue_found", "metadata_insufficient"],
)
def test_all_package_safety_states_validate_in_model_registry_and_draft(status: str) -> None:
    payload = _payload(status)
    receipt = PackageSafetyEvidenceReceipt.model_validate(payload)
    SchemaRegistry().validate("package-safety-evidence.v1", payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))

    assert receipt.status == status
    assert errors == []


def test_reviewed_no_issue_requires_evidence_in_model_and_draft() -> None:
    payload = _payload()
    payload["evidence"] = []

    with pytest.raises(ValidationError, match="requires evidence"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize(
    ("status", "missing_fields"),
    [
        ("reviewed_no_issue", ("evidence",)),
        ("issue_found", ("evidence", "findings", "blockers")),
        ("metadata_insufficient", ("blockers",)),
    ],
)
def test_state_required_fields_cannot_be_omitted_in_any_validation_lane(
    status: str,
    missing_fields: tuple[str, ...],
) -> None:
    payload = _payload(status)
    for field in missing_fields:
        payload.pop(field)

    with pytest.raises(ValidationError):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_issue_found_rejects_info_only_findings_in_model_and_draft() -> None:
    payload = _payload("issue_found")
    findings = payload["findings"]
    assert isinstance(findings, list)
    findings[0]["severity"] = "info"

    with pytest.raises(ValidationError, match="warning or blocker"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_findings_must_reference_supplied_evidence_ids() -> None:
    payload = _payload("issue_found")
    findings = payload["findings"]
    assert isinstance(findings, list)
    findings[0]["evidence_ids"] = ["missing-report"]

    with pytest.raises(ValidationError, match="supplied evidence ids"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_blockers_must_reference_supplied_digest_bound_evidence() -> None:
    payload = _payload("issue_found")
    blocker = payload["blocker"]
    blockers = payload["blockers"]
    assert isinstance(blocker, dict)
    assert isinstance(blockers, list)
    blocker["evidence_refs"] = ["evidence/not-supplied.json"]
    blockers[0] = blocker

    with pytest.raises(ValidationError, match="digest-bound evidence"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_schema_names_structural_only_package_safety_semantics() -> None:
    schema = SchemaRegistry().load("package-safety-evidence.v1")

    assert schema["$comment"] == (
        "Validate evidence-id references, unique finding codes, and primary blocker ordering with "
        "skills_sdk.core.schema_registry.SchemaRegistry.validate."
    )
    assert schema["x-skills-sdk-semantic-validator"] == {
        "entrypoint": "skills_sdk.core.schema_registry.SchemaRegistry.validate",
        "required_for": [
            "findings must reference supplied evidence ids",
            "finding codes, evidence ids, and evidence refs must be unique",
            "issue and insufficient states must retain the primary blocker first",
            "blocker evidence refs must resolve to supplied digest-bound evidence",
        ],
        "external_entrypoint": (
            "skills_sdk.core.schema_registry.SchemaRegistry.validate_package_safety_evidence_against_package_receipt"
        ),
        "external_inputs_required_for": [
            "input receipt id, candidate, and package digest must match a supplied package-receipt/v2",
        ],
    }

    missing_evidence_id = _payload("issue_found")
    missing_evidence_findings = missing_evidence_id["findings"]
    assert isinstance(missing_evidence_findings, list)
    missing_evidence_findings[0]["evidence_ids"] = ["missing-report"]

    missing_evidence_ref = _payload("issue_found")
    missing_ref_blocker = missing_evidence_ref["blocker"]
    missing_ref_blockers = missing_evidence_ref["blockers"]
    assert isinstance(missing_ref_blocker, dict)
    assert isinstance(missing_ref_blockers, list)
    missing_ref_blocker["evidence_refs"] = ["evidence/not-supplied.json"]
    missing_ref_blockers[0] = missing_ref_blocker

    primary_not_first = _payload("issue_found")
    primary_blocker = primary_not_first["blocker"]
    primary_blockers = primary_not_first["blockers"]
    assert isinstance(primary_blocker, dict)
    assert isinstance(primary_blockers, list)
    secondary = deepcopy(primary_blocker)
    secondary["code"] = "secondary_review"
    secondary["message"] = "secondary review blocker"
    primary_not_first["blockers"] = [secondary, primary_blocker]

    for payload in (missing_evidence_id, missing_evidence_ref, primary_not_first):
        assert not list(Draft202012Validator(schema).iter_errors(payload))
        with pytest.raises(ValidationError):
            PackageSafetyEvidenceReceipt.model_validate(payload)
        with pytest.raises(ContractError, match="contract_validation_failed"):
            SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_safety_receipt_accepts_upstream_manifest_digest_distinct_from_source_identity() -> None:
    payload = _payload()
    upstream_receipt = PackageReceiptV2.model_validate(
        json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))
    )
    assert upstream_receipt.candidate is not None
    assert upstream_receipt.package_digest is not None
    assert upstream_receipt.package_digest != upstream_receipt.candidate.content_sha256
    payload["candidate"] = upstream_receipt.candidate.model_dump(mode="json")
    payload["input_receipt_id"] = upstream_receipt.receipt_id
    payload["package_digest"] = upstream_receipt.package_digest
    schema = SchemaRegistry().load("package-safety-evidence.v1")

    assert not list(Draft202012Validator(schema).iter_errors(payload))
    receipt = PackageSafetyEvidenceReceipt.model_validate(payload)
    SchemaRegistry().validate("package-safety-evidence.v1", payload)
    assert receipt.input_receipt_id == upstream_receipt.receipt_id
    assert receipt.package_digest == upstream_receipt.package_digest
    receipt.validate_against_package_receipt(upstream_receipt)
    SchemaRegistry().validate_package_safety_evidence_against_package_receipt(payload, upstream_receipt)


@pytest.mark.parametrize("field", ["input_receipt_id", "candidate", "package_digest"])
def test_safety_receipt_rejects_mismatched_upstream_package_receipt_binding(field: str) -> None:
    payload = _payload()
    upstream_receipt = PackageReceiptV2.model_validate(
        json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))
    )
    assert upstream_receipt.candidate is not None
    assert upstream_receipt.package_digest is not None
    payload["candidate"] = upstream_receipt.candidate.model_dump(mode="json")
    payload["input_receipt_id"] = upstream_receipt.receipt_id
    payload["package_digest"] = upstream_receipt.package_digest
    if field == "input_receipt_id":
        payload[field] = "other-package-receipt"
    elif field == "candidate":
        payload[field] = {**payload[field], "content_sha256": "b" * 64}
    else:
        payload[field] = "b" * 64

    safety_receipt = PackageSafetyEvidenceReceipt.model_validate(payload)
    with pytest.raises(ValueError, match="upstream package receipt"):
        safety_receipt.validate_against_package_receipt(upstream_receipt)
    with pytest.raises(ContractError, match="upstream package receipt binding"):
        SchemaRegistry().validate_package_safety_evidence_against_package_receipt(payload, upstream_receipt)


def test_duplicate_evidence_refs_fail_semantic_validation() -> None:
    payload = _payload()
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    evidence.append({**evidence[0], "evidence_id": "second-report", "sha256": "d" * 64})
    schema = SchemaRegistry().load("package-safety-evidence.v1")

    assert not list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ValidationError, match="evidence refs must be unique"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_duplicate_blockers_fail_in_model_and_draft() -> None:
    payload = _payload("issue_found")
    blockers = payload["blockers"]
    assert isinstance(blockers, list)
    blockers.append(deepcopy(blockers[0]))

    with pytest.raises(ValidationError, match="blockers must be unique"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize("delimiter", ["=", "@", "%", "#", "$", ":", "/"])
def test_public_safety_fields_reject_credential_shapes_in_model_and_draft(delimiter: str) -> None:
    payload = _payload()
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    evidence[0]["ref"] = f"evidence/token{delimiter}sk-live-secret"

    with pytest.raises(ValidationError, match="credential-shaped"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize("credential_shape", ["ghp_secret", "hf_secret"])
def test_finding_evidence_ids_reject_credential_shapes_at_all_boundaries(credential_shape: str) -> None:
    payload = _payload("issue_found")
    findings = payload["findings"]
    assert isinstance(findings, list)
    findings[0]["evidence_ids"] = [credential_shape]

    with pytest.raises(ValidationError, match="credential-shaped"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_finding_evidence_ids_reject_generator_input_before_coercion() -> None:
    payload = _payload("issue_found")
    findings = payload["findings"]
    assert isinstance(findings, list)
    findings[0]["evidence_ids"] = (value for value in ("ghp_secret",))

    with pytest.raises(ValidationError, match="JSON-compatible containers"):
        PackageSafetyEvidenceReceipt.model_validate(payload)


@pytest.mark.parametrize("target", ["evidence_id", "finding_evidence_id"])
def test_safety_evidence_ids_reject_surrounding_whitespace_at_all_boundaries(target: str) -> None:
    payload = _payload("issue_found")
    evidence = payload["evidence"]
    findings = payload["findings"]
    assert isinstance(evidence, list)
    assert isinstance(findings, list)
    if target == "evidence_id":
        evidence[0]["evidence_id"] = " review-report "
    else:
        findings[0]["evidence_ids"] = [" review-report "]

    with pytest.raises(ValidationError, match="already be normalized"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize("accepted_id", ["ghp-safe", "hf-safe"])
def test_finding_evidence_ids_accept_noncredential_boundaries(accepted_id: str) -> None:
    payload = _payload("issue_found")
    evidence = payload["evidence"]
    findings = payload["findings"]
    assert isinstance(evidence, list)
    assert isinstance(findings, list)
    evidence[0]["evidence_id"] = accepted_id
    findings[0]["evidence_ids"] = [accepted_id]

    PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert not list(Draft202012Validator(schema).iter_errors(payload))
    SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize("credential_shape", ["AIzaSyntheticMarker", "hf_synthetic_marker"])
def test_reviewer_metadata_rejects_established_secret_prefixes_at_all_boundaries(
    credential_shape: str,
) -> None:
    payload = _payload()
    reviewer = payload["reviewer"]
    assert isinstance(reviewer, dict)
    reviewer["adapter_version_or_digest"] = credential_shape

    with pytest.raises(ValidationError, match="credential-shaped"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize(
    "unicode_near_match",
    [
        "\u017fecret=value",
        "ap\u0131_key=value",
        "api_\u212aey=value",
        "\u017fk-live-value",
        "pa\u017f\u017fword=value",
    ],
)
def test_credential_screening_uses_ascii_case_semantics_at_all_boundaries(
    unicode_near_match: str,
) -> None:
    payload = _payload("issue_found")
    findings = payload["findings"]
    assert isinstance(findings, list)
    findings[0]["message"] = unicode_near_match

    PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert not list(Draft202012Validator(schema).iter_errors(payload))
    SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapter_version_or_digest", "/" + "Users/alice/tool"),
        ("adapter_version_or_digest", "C:" + "\\" + "Users\\alice\\tool"),
        ("message", "source at /" + "home/alice/private/skill.md"),
        ("message", "source at /" + "tmp/private.json"),
        ("message", "source at /" + "workspace/private.json"),
        ("message", "source at /" + "var/folders/cache/private.json"),
        ("message", "file:///" + "Users/alice/private/skill.md"),
        ("message", "source at /" + "etc/hosts"),
        ("message", "file:" + "/" * 3 + "opt/tool/config"),
        ("message", "source:" + "/mnt/ci/result.json"),
        ("message", "path:" + "/srv/private/report"),
        ("message", "source at /" + "users/alice/private/skill.md"),
        ("message", "source at /" + "HOME/alice/private/skill.md"),
        ("message", "password=hunter2"),
        ("message", "api_key: synthetic-value"),
    ],
)
def test_public_safety_fields_reject_machine_paths_and_generic_credentials(field: str, value: str) -> None:
    payload = _payload("issue_found")
    if field == "adapter_version_or_digest":
        reviewer = payload["reviewer"]
        assert isinstance(reviewer, dict)
        reviewer[field] = value
    else:
        findings = payload["findings"]
        assert isinstance(findings, list)
        findings[0][field] = value

    with pytest.raises(ValidationError):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize("target", ["evidence_ref", "blocker_evidence_ref"])
def test_embedded_machine_paths_fail_in_model_draft_and_registry(target: str) -> None:
    payload = _payload("issue_found" if target == "blocker_evidence_ref" else "reviewed_no_issue")
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    machine_path = "evidence/" + "Users/alice/private.json"
    evidence[0]["ref"] = machine_path
    if target == "blocker_evidence_ref":
        blocker = payload["blocker"]
        blockers = payload["blockers"]
        assert isinstance(blocker, dict)
        assert isinstance(blockers, list)
        blocker["evidence_refs"] = [machine_path]
        blockers[0] = blocker

    with pytest.raises(ValidationError):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "source at C:" + "\\" + "workspace\\project\\result.json",
        "source at D:/build/agent/result.json",
        "source at C:relative" + "\\" + "result.json",
        "source at Z:folder/file.txt",
        "source at /" + "root/project/result.json",
        "AWS_" + "SE" + "CRET" + "_ACCESS_KEY=opaque-value",
        "token\u00a0=opaque-value",
        "token\u0085=opaque-value",
    ],
)
def test_extended_machine_paths_and_unicode_credential_spacing_fail_at_all_boundaries(
    unsafe_text: str,
) -> None:
    payload = _payload("issue_found")
    findings = payload["findings"]
    assert isinstance(findings, list)
    findings[0]["message"] = unsafe_text

    with pytest.raises(ValidationError, match="credential-shaped"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "-----BEGIN " + "PRIVATE KEY----- synthetic",
        "source at " + "\\" * 2 + "server" + "\\" + "share" + "\\" + "private" + "\\" + "skill.md",
    ],
)
def test_public_safety_fields_reject_private_key_markers_and_unc_paths(unsafe_text: str) -> None:
    payload = _payload("issue_found")
    findings = payload["findings"]
    assert isinstance(findings, list)
    findings[0]["message"] = unsafe_text

    with pytest.raises(ValidationError):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "-----" + "BEGIN rsa PRIVATE KEY----- synthetic",
        "SSH_" + "PRIVATE_KEY=opaque-value",
        "private_key=opaque-value",
    ],
)
def test_public_safety_fields_reject_case_insensitive_private_key_values(unsafe_text: str) -> None:
    payload = _payload("issue_found")
    findings = payload["findings"]
    assert isinstance(findings, list)
    findings[0]["message"] = unsafe_text

    with pytest.raises(ValidationError, match="credential-shaped"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_safety_receipt_rejects_cyclic_adapter_payloads() -> None:
    payload = _payload()
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    evidence.append(evidence)

    with pytest.raises(ValidationError, match="cyclic containers"):
        PackageSafetyEvidenceReceipt.model_validate(payload)


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "source at " + "\\" + "server\\share\\private\\skill.md",
        "source at /etc/hosts",
        "source at file:///opt/tool/config",
    ],
)
def test_public_safety_fields_reject_rooted_host_paths_at_all_boundaries(unsafe_text: str) -> None:
    payload = _payload("issue_found")
    findings = payload["findings"]
    assert isinstance(findings, list)
    findings[0]["message"] = unsafe_text

    with pytest.raises(ValidationError):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize("target", ["finding", "blocker"])
def test_safety_messages_reject_whitespace_only_at_all_boundaries(target: str) -> None:
    payload = _payload("issue_found")
    if target == "finding":
        findings = payload["findings"]
        assert isinstance(findings, list)
        findings[0]["message"] = " \t "
    else:
        blocker = payload["blocker"]
        blockers = payload["blockers"]
        assert isinstance(blocker, dict)
        assert isinstance(blockers, list)
        blocker["message"] = " \t "
        blockers[0] = blocker

    with pytest.raises(ValidationError):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_safety_observed_at_requires_datetime_format_at_all_boundaries() -> None:
    payload = _payload()
    payload["observed_at"] = "not-a-datetime"

    with pytest.raises(ValidationError):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_safety_observed_at_rejects_non_string_inputs_at_all_boundaries() -> None:
    payload = _payload()
    payload["observed_at"] = 0

    with pytest.raises(ValidationError, match="observed_at must be an RFC3339 string"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize("target", ["finding", "blocker"])
def test_safety_codes_reject_surrounding_whitespace_at_all_boundaries(target: str) -> None:
    payload = _payload("issue_found")
    if target == "finding":
        findings = payload["findings"]
        assert isinstance(findings, list)
        findings[0]["code"] = " unsafe_operation "
    else:
        blocker = payload["blocker"]
        blockers = payload["blockers"]
        assert isinstance(blocker, dict)
        assert isinstance(blockers, list)
        blocker["code"] = " issue_found "
        blockers[0] = blocker

    with pytest.raises(ValidationError, match="code must already be normalized"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize("target", ["reviewer", "evidence", "finding", "blocker", "receipt_id"])
def test_public_safety_fields_reject_byte_strings_at_all_boundaries(target: str) -> None:
    payload = _payload("issue_found")
    unsafe_value = b"password=synthetic-value"
    if target == "reviewer":
        reviewer = payload["reviewer"]
        assert isinstance(reviewer, dict)
        reviewer["adapter_version_or_digest"] = unsafe_value
    elif target == "evidence":
        evidence = payload["evidence"]
        assert isinstance(evidence, list)
        evidence[0]["evidence_id"] = unsafe_value
    elif target == "finding":
        findings = payload["findings"]
        assert isinstance(findings, list)
        findings[0]["message"] = unsafe_value
    elif target == "blocker":
        blocker = payload["blocker"]
        blockers = payload["blockers"]
        assert isinstance(blocker, dict)
        assert isinstance(blockers, list)
        blocker["message"] = unsafe_value
        blockers[0] = blocker
    else:
        payload["receipt_id"] = unsafe_value

    with pytest.raises(ValidationError, match="must not coerce byte strings"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="invalid_json_value"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_public_safety_fields_accept_non_file_urls_at_all_boundaries() -> None:
    payload = _payload("issue_found")
    findings = payload["findings"]
    assert isinstance(findings, list)
    findings[0]["message"] = "Reference https://example.test/tmp/safety-guidance"

    PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert not list(Draft202012Validator(schema).iter_errors(payload))
    SchemaRegistry().validate("package-safety-evidence.v1", payload)


def test_safety_receipt_requires_lane_at_all_boundaries() -> None:
    payload = _payload()
    payload.pop("lane")

    with pytest.raises(ValidationError):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        parse_receipt(payload)


def test_safety_receipt_requires_schema_version_at_all_boundaries() -> None:
    payload = _payload()
    payload.pop("schema_version")

    with pytest.raises(ValidationError):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)
    with pytest.raises(ContractError, match="invalid_receipt_schema_version"):
        parse_receipt(payload)


def test_package_safety_contract_rejects_generic_safe_boolean() -> None:
    payload = _payload()
    payload["safe"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)


@pytest.mark.parametrize("field", ["receipt_id", "input_receipt_id"])
def test_safety_receipt_ids_reject_credential_shapes_at_all_boundaries(field: str) -> None:
    payload = _payload()
    payload[field] = "ghp_secret_marker"

    with pytest.raises(ValidationError, match="credential-shaped"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        parse_receipt(payload)


@pytest.mark.parametrize("field", ["receipt_id", "input_receipt_id"])
def test_safety_receipt_ids_reject_surrounding_whitespace_at_all_boundaries(field: str) -> None:
    payload = _payload()
    payload[field] = f" {payload[field]} "

    with pytest.raises(ValidationError, match="already be normalized"):
        PackageSafetyEvidenceReceipt.model_validate(payload)
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-safety-evidence.v1", payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        parse_receipt(payload)


@pytest.mark.parametrize(
    ("status", "generic_status"),
    [
        ("not_reviewed", "blocked"),
        ("reviewed_no_issue", "pass"),
        ("issue_found", "blocked"),
        ("metadata_insufficient", "blocked"),
    ],
)
def test_generic_parser_preserves_safety_state_and_immutable_payload(status: str, generic_status: str) -> None:
    payload = _payload(status)
    original = deepcopy(payload)

    receipt = parse_receipt(payload)
    payload["status"] = "not_reviewed"

    assert receipt.status == generic_status
    assert receipt.artifact_status == status
    assert receipt.candidate is not None
    assert receipt.candidate.package_id == "synthetic-skill"
    assert receipt.evidence == tuple(item["ref"] for item in original["evidence"] if isinstance(item, dict))
    assert receipt.payload["status"] == status
    if status == "not_reviewed":
        assert receipt.blocker is not None
        assert receipt.blocker.code == "not_reviewed"
        assert receipt.blocker.message == "package safety review was not performed"
        assert receipt.blocker.evidence_refs == ()


def test_safety_contract_does_not_reinterpret_existing_receipt_families() -> None:
    with pytest.raises(ContractError, match="unsupported_receipt_family"):
        parse_receipt({"schema_version": "package-safety-evidence/v2"})
    with pytest.raises(ContractError, match="invalid_receipt_schema_version"):
        parse_receipt({"schema_version": None})
