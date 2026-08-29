from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.distribution import prepare_private_registry_candidate
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageHardeningCheck, PackageReceiptBlocker, PackageReceiptV2
from skills_sdk.models.registry import RegistryIdentity, RegistryPreparationReceipt, RegistryPreparationRequest
from skills_sdk.packaging import harden_skill_package

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "package-receipts"


def _package_receipt() -> PackageReceiptV2:
    payload = json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))
    return PackageReceiptV2.model_validate(payload)


def _prepare(
    package_receipt: PackageReceiptV2,
    *,
    package_name: str = "synthetic-skill",
    version: str = "0.1.0",
    evidence: tuple[str, ...] = ("evidence/private-registry-preparation.json",),
) -> RegistryPreparationReceipt:
    return prepare_private_registry_candidate(
        package_receipt,
        harden_skill_package(package_receipt),
        RegistryPreparationRequest(
            registry=RegistryIdentity(registry_id="private-registry", namespace="example-team"),
            package_name=package_name,
            version=version,
            evidence=evidence,
        ),
    )


def test_preparation_is_deterministic_bound_and_non_publishing() -> None:
    package_receipt = _package_receipt()
    first = _prepare(package_receipt)
    second = _prepare(package_receipt)
    assert first == second
    assert first.status == "prepared"
    assert first.candidate == package_receipt.candidate
    assert first.package_digest == package_receipt.package_digest
    assert first.manifest_digest == package_receipt.package_digest
    assert first.hardening_receipt_sha256 is not None
    assert first.mutation_performed is False
    assert first.publication_performed is False


def test_preparation_identity_binds_evidence_and_registry() -> None:
    package_receipt = _package_receipt()
    first = _prepare(package_receipt)
    changed_evidence = _prepare(package_receipt, evidence=("evidence/other.json",))
    changed_registry = prepare_private_registry_candidate(
        package_receipt,
        harden_skill_package(package_receipt),
        RegistryPreparationRequest(
            registry=RegistryIdentity(registry_id="private-registry", namespace="other-team"),
            package_name="synthetic-skill",
            version="0.1.0",
            evidence=("evidence/private-registry-preparation.json",),
        ),
    )
    assert first.receipt_id != changed_evidence.receipt_id
    assert first.receipt_id != changed_registry.receipt_id


def test_preparation_rejects_duplicate_evidence_paths() -> None:
    with pytest.raises(ValidationError, match="evidence paths must be unique"):
        _prepare(
            _package_receipt(),
            evidence=("evidence/result.json", "evidence/result.json"),
        )


def test_blocked_package_receipt_stays_blocked_without_digest_claims() -> None:
    payload = json.loads((FIXTURE_ROOT / "blocked-v2.json").read_text(encoding="utf-8"))
    package_receipt = PackageReceiptV2.model_validate(payload)
    result = _prepare(package_receipt)
    assert result.status == "blocked"
    assert result.blocker is not None
    assert result.package_digest is None
    assert result.manifest_digest is None
    assert result.hardening_receipt_sha256 is None


def test_credential_shaped_package_blocker_metadata_is_redacted() -> None:
    payload = json.loads((FIXTURE_ROOT / "blocked-v2.json").read_text(encoding="utf-8"))
    package_receipt = PackageReceiptV2.model_validate(payload).model_copy(
        update={
            "blocker": PackageReceiptBlocker(
                code="ghp_secret_marker",
                message="blocked@sk-live-secret",
                evidence_refs=("evidence/safe.json",),
            )
        }
    )
    result = _prepare(package_receipt)

    assert package_receipt.blocker is not None
    assert result.blocker is not None
    assert result.blocker.code == "source_blocker_redacted"
    assert result.blocker.evidence_refs == ("evidence/safe.json",)
    assert result.blocker.source_blocker_sha256 == canonical_json_sha256(
        package_receipt.blocker.model_dump(mode="json")
    )
    assert "ghp_secret_marker" not in result.model_dump_json()
    assert "blocked@sk-live-secret" not in result.model_dump_json()


def test_hardening_identity_mismatch_is_typed_and_identity_bound() -> None:
    package_receipt = _package_receipt()
    hardening = harden_skill_package(package_receipt)
    assert hardening.candidate is not None
    other = PackageCandidateIdentity(
        package_id="synthetic-skill",
        source_revision="2" * 40,
        content_sha256="d" * 64,
    )
    unrelated_warning = PackageHardeningCheck(
        id="unrelated_warning",
        status="warning",
        message="warning from a different candidate",
    )
    mismatched = hardening.model_copy(
        update={
            "candidate": other,
            "hardening_checks": (*hardening.hardening_checks, unrelated_warning),
            "warnings": (unrelated_warning,),
        }
    )
    result = prepare_private_registry_candidate(
        package_receipt,
        mismatched,
        RegistryPreparationRequest(
            registry=RegistryIdentity(registry_id="private-registry", namespace="example-team"),
            package_name="synthetic-skill",
            version="0.1.0",
            evidence=("evidence/private-registry-preparation.json",),
        ),
    )
    assert result.status == "blocked"
    assert result.blocker is not None
    assert result.blocker.code == "hardening_identity_mismatch"
    assert result.hardening_receipt_sha256 is None
    assert result.warnings == ()


def test_blocked_identity_binds_complete_hardening_receipt() -> None:
    package_receipt = _package_receipt()
    hardening = harden_skill_package(package_receipt)
    assert hardening.candidate is not None
    first_candidate = hardening.candidate.model_copy(update={"source_revision": "2" * 40})
    second_candidate = hardening.candidate.model_copy(update={"source_revision": "3" * 40})
    first = prepare_private_registry_candidate(
        package_receipt,
        hardening.model_copy(update={"candidate": first_candidate}),
        RegistryPreparationRequest(
            registry=RegistryIdentity(registry_id="private-registry", namespace="example-team"),
            package_name="synthetic-skill",
            version="0.1.0",
            evidence=("evidence/private-registry-preparation.json",),
        ),
    )
    second = prepare_private_registry_candidate(
        package_receipt,
        hardening.model_copy(update={"candidate": second_candidate}),
        RegistryPreparationRequest(
            registry=RegistryIdentity(registry_id="private-registry", namespace="example-team"),
            package_name="synthetic-skill",
            version="0.1.0",
            evidence=("evidence/private-registry-preparation.json",),
        ),
    )
    assert first.receipt_id != second.receipt_id


def test_manifest_version_mismatch_is_typed_blocker() -> None:
    result = _prepare(_package_receipt(), version="9.9.9")
    assert result.status == "blocked"
    assert result.blocker is not None
    assert result.blocker.code == "package_version_mismatch"


def test_package_name_mismatch_is_typed_blocker() -> None:
    result = _prepare(_package_receipt(), package_name="different-skill")
    assert result.status == "blocked"
    assert result.blocker is not None
    assert result.blocker.code == "package_name_mismatch"
    assert result.package_digest is None
    assert result.manifest_digest is None
    assert result.hardening_receipt_sha256 is None
    assert result.publication_performed is False


def test_valid_long_package_id_returns_typed_registry_blocker() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))
    long_package_id = "p" * 65
    payload["candidate"]["package_id"] = long_package_id
    payload["manifest"]["candidate"]["package_id"] = long_package_id
    payload["package_digest"] = canonical_json_sha256(payload["manifest"])
    package_receipt = PackageReceiptV2.model_validate(payload)

    result = _prepare(package_receipt, package_name=long_package_id)
    assert result.status == "blocked"
    assert result.blocker is not None
    assert result.blocker.code == "registry_package_name_unsupported"
    assert result.package_digest is None
    assert result.publication_performed is False


def test_valid_non_semver_package_version_returns_typed_registry_blocker() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8"))
    payload["manifest"]["version"] = "release"
    payload["package_digest"] = canonical_json_sha256(payload["manifest"])
    package_receipt = PackageReceiptV2.model_validate(payload)

    result = _prepare(package_receipt, version="release")
    assert result.status == "blocked"
    assert result.blocker is not None
    assert result.blocker.code == "registry_version_unsupported"
    assert result.package_digest is None
    assert result.publication_performed is False


def test_all_hardening_blockers_and_evidence_are_preserved_deterministically() -> None:
    package_receipt = _package_receipt()
    baseline = harden_skill_package(package_receipt)
    first_blocker = PackageHardeningCheck(
        id="hardening_blocked",
        status="blocker",
        message="hardening blocked",
        evidence=("evidence/hardening-first.json",),
    )
    second_blocker = PackageHardeningCheck(
        id="provenance_blocked",
        status="blocker",
        message="provenance blocked",
        evidence=("sensor:policy",),
    )
    blockers = (first_blocker, second_blocker)
    warning = PackageHardeningCheck(
        id="budget_warning",
        status="warning",
        message="warning contains sk-live-secret",
        evidence=("ghp_synthetic-secret",),
    )
    hardening = baseline.model_copy(
        update={
            "status": "blocked",
            "hardening_checks": (*baseline.hardening_checks, *blockers, warning),
            "blockers": blockers,
            "warnings": (warning,),
        }
    )
    request = RegistryPreparationRequest(
        registry=RegistryIdentity(registry_id="private-registry", namespace="example-team"),
        package_name="synthetic-skill",
        version="0.1.0",
        evidence=("evidence/private-registry-preparation.json",),
    )
    first = prepare_private_registry_candidate(
        package_receipt,
        hardening,
        request,
    )
    second = prepare_private_registry_candidate(
        package_receipt,
        hardening,
        request,
    )

    assert first == second
    assert first.status == "blocked"
    assert first.blocker == first.blockers[0]
    assert [(item.code, item.evidence_refs) for item in first.blockers] == [
        ("hardening_blocked", ("evidence/hardening-first.json",)),
        ("provenance_blocked", ()),
    ]
    assert [item.source_evidence_sha256 for item in first.blockers] == [
        (),
        (canonical_json_sha256("sensor:policy"),),
    ]
    assert first.warnings[0].warning_sha256 == canonical_json_sha256(warning.model_dump(mode="json"))
    assert first.warnings[0].evidence_refs == ()
    assert first.warnings[0].source_evidence_sha256 == (canonical_json_sha256("ghp_synthetic-secret"),)
    assert "sk-live-secret" not in first.model_dump_json()
    assert "ghp_synthetic-secret" not in first.model_dump_json()
    assert first.publication_performed is False


def test_credential_shaped_hardening_evidence_is_digest_bound_not_exposed() -> None:
    package_receipt = _package_receipt()
    baseline = harden_skill_package(package_receipt)
    blocker = PackageHardeningCheck(
        id="policy_blocked",
        status="blocker",
        message="policy blocked",
        evidence=("token=sk-live-secret",),
    )
    hardening = baseline.model_copy(
        update={
            "status": "blocked",
            "hardening_checks": (*baseline.hardening_checks, blocker),
            "blockers": (blocker,),
        }
    )
    result = prepare_private_registry_candidate(
        package_receipt,
        hardening,
        RegistryPreparationRequest(
            registry=RegistryIdentity(registry_id="private-registry", namespace="example-team"),
            package_name="synthetic-skill",
            version="0.1.0",
            evidence=("evidence/private-registry-preparation.json",),
        ),
    )

    assert result.status == "blocked"
    assert result.blocker is not None
    assert result.blocker.evidence_refs == ()
    assert result.blocker.source_evidence_sha256 == (canonical_json_sha256("token=sk-live-secret"),)
    assert "token=sk-live-secret" not in result.model_dump_json()


def test_credential_shaped_blocker_metadata_is_redacted_and_digest_bound() -> None:
    package_receipt = _package_receipt()
    baseline = harden_skill_package(package_receipt)
    blocker = PackageHardeningCheck(
        id="ghp_secret_marker",
        status="blocker",
        message="blocked#sk-live-secret",
        evidence=("evidence/safe.json",),
    )
    hardening = baseline.model_copy(
        update={
            "status": "blocked",
            "hardening_checks": (*baseline.hardening_checks, blocker),
            "blockers": (blocker,),
        }
    )
    result = prepare_private_registry_candidate(
        package_receipt,
        hardening,
        RegistryPreparationRequest(
            registry=RegistryIdentity(registry_id="private-registry", namespace="example-team"),
            package_name="synthetic-skill",
            version="0.1.0",
            evidence=("evidence/private-registry-preparation.json",),
        ),
    )

    assert result.blocker is not None
    assert result.blocker.code == "source_blocker_redacted"
    assert result.blocker.source_blocker_sha256 == canonical_json_sha256(blocker.model_dump(mode="json"))
    assert result.blocker.evidence_refs == ("evidence/safe.json",)
    assert "ghp_secret_marker" not in result.model_dump_json()
    assert "blocked#sk-live-secret" not in result.model_dump_json()


def test_prepared_warning_is_digest_bound_and_secret_free() -> None:
    package_receipt = _package_receipt()
    baseline = harden_skill_package(package_receipt)
    warning = PackageHardeningCheck(
        id="budget_warning",
        status="warning",
        message="warning$sk-live-secret",
        evidence=("evidence/safe.json", "token=ghp_synthetic-secret"),
    )
    hardening = baseline.model_copy(
        update={
            "hardening_checks": (*baseline.hardening_checks, warning),
            "warnings": (warning,),
        }
    )
    result = prepare_private_registry_candidate(
        package_receipt,
        hardening,
        RegistryPreparationRequest(
            registry=RegistryIdentity(registry_id="private-registry", namespace="example-team"),
            package_name="synthetic-skill",
            version="0.1.0",
            evidence=("evidence/private-registry-preparation.json",),
        ),
    )

    assert result.status == "prepared"
    assert result.warnings[0].warning_sha256 == canonical_json_sha256(warning.model_dump(mode="json"))
    assert result.warnings[0].evidence_refs == ("evidence/safe.json",)
    assert result.warnings[0].source_evidence_sha256 == (canonical_json_sha256("token=ghp_synthetic-secret"),)
    assert "warning$sk-live-secret" not in result.model_dump_json()
    assert "token=ghp_synthetic-secret" not in result.model_dump_json()


def test_preparation_module_has_no_host_or_network_dependencies() -> None:
    source = (Path(__file__).parents[1] / "src/skills_sdk/distribution/private_registry.py").read_text(encoding="utf-8")
    for forbidden in ("requests", "httpx", "socket", "subprocess", "os.environ", "write_text", "open("):
        assert forbidden not in source
