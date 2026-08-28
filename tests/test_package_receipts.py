from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.receipts import CandidateIdentity, Receipt, parse_receipt
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceipt, PackageReceiptV2

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "package-receipts"


def _candidate() -> PackageCandidateIdentity:
    return PackageCandidateIdentity(
        package_id="synthetic-skill",
        source_revision="1" * 40,
        content_sha256="a" * 64,
    )


def test_built_receipt_fixture_is_candidate_bound() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    receipt = PackageReceipt.model_validate(payload)
    assert receipt.status == "built"
    assert receipt.manifest is not None
    assert receipt.manifest.candidate == receipt.candidate
    assert set(receipt.included_files) == {"README.md", "SKILL.md"}
    assert receipt.mutation_performed is False


def test_v1_receipt_preserves_opaque_digest_compatibility() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))

    receipt = PackageReceipt.model_validate(payload)

    assert receipt.package_digest == "b" * 64
    SchemaRegistry().validate("package-receipt.v1", payload)


def test_v2_receipt_binds_digest_to_canonical_manifest() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))

    receipt = PackageReceiptV2.model_validate(payload)

    assert receipt.status == "built"
    SchemaRegistry().validate("package-receipt.v2", payload)


def test_v2_package_receipt_preserves_v1_python_inheritance() -> None:
    assert issubclass(PackageReceiptV2, PackageReceipt)


def test_blocked_receipt_fixture_requires_an_explicit_blocker() -> None:
    payload = json.loads((FIXTURE_ROOT / "blocked.json").read_text(encoding="utf-8"))
    receipt = PackageReceipt.model_validate(payload)
    assert receipt.status == "blocked"
    assert receipt.blocker is not None
    assert receipt.blocker.code == "unsafe_path"


def test_package_receipt_is_available_through_generic_parser() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    receipt = parse_receipt(payload)
    assert receipt.receipt_id == "synthetic-package-receipt-1"
    assert receipt.lane == "validation"
    assert receipt.status == "pass"
    assert receipt.artifact_status == "built"
    assert receipt.payload["status"] == "built"
    assert receipt.candidate is not None
    assert receipt.candidate.package_id == "synthetic-skill"


def test_v2_package_receipt_is_available_through_generic_parser() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))

    receipt = parse_receipt(payload)

    assert receipt.receipt_id == "synthetic-package-receipt-2"
    assert receipt.status == "pass"
    assert receipt.artifact_status == "built"


def test_generic_parser_rejects_non_string_schema_version_as_typed_contract_error() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))
    payload["schema_version"] = []

    with pytest.raises(ContractError) as error:
        parse_receipt(payload)

    assert error.value.code == "invalid_receipt_schema_version"


def test_package_receipt_payload_is_deeply_immutable() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    receipt = parse_receipt(payload)
    payload["manifest"]["candidate"]["source_revision"] = "2" * 40
    assert receipt.payload["manifest"]["candidate"]["source_revision"] == "1" * 40
    with pytest.raises(TypeError):
        receipt.payload["manifest"]["candidate"]["source_revision"] = "3" * 40


def test_generic_receipt_constructor_keeps_artifact_status_optional() -> None:
    candidate = CandidateIdentity(
        package_id="synthetic-skill",
        source_revision="1" * 40,
        content_sha256="a" * 64,
    )
    receipt = Receipt("receipt-1", candidate, "validation", "pass", (), None, {})
    assert receipt.artifact_status is None


def test_blocked_package_receipt_allows_blocker_without_evidence_refs() -> None:
    payload = json.loads((FIXTURE_ROOT / "blocked.json").read_text(encoding="utf-8"))
    payload["blocker"].pop("evidence_refs")
    receipt = parse_receipt(payload)
    assert receipt.blocker is not None
    assert receipt.blocker.evidence_refs == ()


@pytest.mark.parametrize("candidate_value", [None, "missing"])
def test_generic_parser_preserves_unresolved_blocked_candidate(candidate_value: object) -> None:
    payload = json.loads((FIXTURE_ROOT / "blocked.json").read_text(encoding="utf-8"))
    if candidate_value == "missing":
        payload.pop("candidate")
    else:
        payload["candidate"] = candidate_value

    receipt = parse_receipt(payload)

    assert receipt.candidate is None
    with pytest.raises(ContractError, match="candidate_unavailable"):
        receipt.require_candidate(
            CandidateIdentity(
                package_id="synthetic-skill",
                source_revision="1" * 40,
                content_sha256="a" * 64,
            )
        )


@pytest.mark.parametrize("field", ["schema_version", "lane"])
def test_package_receipt_requires_routing_fields(field: str) -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload.pop(field)
    with pytest.raises(ValidationError):
        PackageReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-receipt.v1", payload)


def test_manifest_and_receipt_must_bind_same_candidate() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["manifest"]["candidate"]["source_revision"] = "2" * 40
    with pytest.raises(ValidationError, match="same candidate"):
        PackageReceipt.model_validate(payload)


def test_v2_built_receipt_rejects_manifest_digest_mismatch() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))
    payload["manifest"]["version"] = "9.9.9"

    with pytest.raises(ValidationError, match="digest must match"):
        PackageReceiptV2.model_validate(payload)
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("package-receipt.v2", payload)
    assert any("digest must match" in detail for detail in error.value.details)


def test_v2_built_receipt_rejects_recomputed_digest_for_wrong_candidate_content() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))
    payload["manifest"]["files"][0]["sha256"] = "f" * 64
    payload["package_digest"] = canonical_json_sha256(payload["manifest"])

    with pytest.raises(ValidationError, match="candidate digest must match manifest files"):
        PackageReceiptV2.model_validate(payload)
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("package-receipt.v2", payload)
    assert any("candidate digest must match manifest files" in detail for detail in error.value.details)


def test_v1_built_receipt_keeps_historical_digest_semantics() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["manifest"]["version"] = "9.9.9"

    PackageReceipt.model_validate(payload)
    SchemaRegistry().validate("package-receipt.v1", payload)


def test_v2_blocked_receipt_does_not_require_a_manifest_digest() -> None:
    payload = json.loads((FIXTURE_ROOT / "blocked-v2.json").read_text(encoding="utf-8"))

    receipt = PackageReceiptV2.model_validate(payload)

    assert receipt.status == "blocked"
    assert receipt.package_digest is None
    SchemaRegistry().validate("package-receipt.v2", payload)


def test_built_receipt_cannot_omit_manifest_files() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["included_files"] = ["SKILL.md"]
    with pytest.raises(ValidationError, match="every manifest path"):
        PackageReceipt.model_validate(payload)


def test_blocked_receipt_can_be_emitted_before_manifest_exists() -> None:
    payload = json.loads((FIXTURE_ROOT / "blocked.json").read_text(encoding="utf-8"))
    payload["manifest"] = None
    payload["included_files"] = []
    payload["excluded_files"] = []
    receipt = PackageReceipt.model_validate(payload)
    assert receipt.package_digest is None
    assert receipt.blocker is not None


def test_blocked_receipt_included_files_must_be_in_manifest() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["status"] = "blocked"
    payload["package_digest"] = None
    payload["blocker"] = {"code": "unsafe_path", "message": "blocked", "evidence_refs": []}
    payload["included_files"] = ["missing.md"]
    with pytest.raises(ValidationError, match="must be manifested"):
        PackageReceipt.model_validate(payload)


def test_receipt_finished_at_must_not_precede_started_at() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["finished_at"] = "2026-08-25T09:59:59Z"
    with pytest.raises(ValidationError, match="finished_at"):
        PackageReceipt.model_validate(payload)


def test_receipt_timestamps_require_timezone() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["started_at"] = datetime(2026, 8, 25, 10, 0, 0)
    with pytest.raises(ValidationError):
        PackageReceipt.model_validate(payload)


def test_package_candidate_is_not_a_machine_path() -> None:
    candidate = _candidate()
    assert candidate.package_id == "synthetic-skill"


def test_schema_registry_rejects_receipt_candidate_mismatch() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["manifest"]["candidate"]["source_revision"] = "2" * 40
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("package-receipt.v1", payload)
    assert any("same candidate" in detail for detail in error.value.details)


def test_schema_registry_rejects_receipt_missing_manifest_path() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["included_files"] = ["SKILL.md"]
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("package-receipt.v1", payload)
    assert any("every manifest path" in detail for detail in error.value.details)


def test_schema_registry_requires_manifest_schema_version() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))["manifest"]
    payload.pop("schema_version")
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-manifest.v1", payload)


def test_blocked_receipt_rejects_excluded_manifest_path() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["status"] = "blocked"
    payload["package_digest"] = None
    payload["blocker"] = {"code": "unsafe_path", "message": "blocked", "evidence_refs": []}
    payload["included_files"] = []
    payload["excluded_files"] = ["SKILL.md"]
    with pytest.raises(ValidationError, match="excluded files must not be manifested"):
        PackageReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-receipt.v1", payload)


def test_schema_registry_rejects_built_receipt_without_included_files() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload.pop("included_files")
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-receipt.v1", payload)


def test_schema_registry_rejects_null_built_artifacts() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["package_digest"] = None
    payload["manifest"] = None
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-receipt.v1", payload)


def test_schema_registry_accepts_explicit_null_built_blocker() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["blocker"] = None
    receipt = PackageReceipt.model_validate(payload)
    SchemaRegistry().validate("package-receipt.v1", payload)
    assert receipt.blocker is None


def test_schema_registry_rejects_duplicate_manifest_paths() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))["manifest"]
    payload["files"].append(dict(payload["files"][0]))
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("package-manifest.v1", payload)
    assert any("paths must be unique" in detail for detail in error.value.details)


def test_schema_registry_rejects_blocked_receipt_without_blocker() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["status"] = "blocked"
    payload["package_digest"] = None
    payload["manifest"] = None
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("package-receipt.v1", payload)
