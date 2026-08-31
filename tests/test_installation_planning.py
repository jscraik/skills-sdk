from __future__ import annotations

import json
from pathlib import Path

from skills_sdk.distribution import prepare_private_registry_candidate
from skills_sdk.lifecycle import plan_runtime_install
from skills_sdk.models.lifecycle import RuntimeLock, RuntimeTarget
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceiptV2
from skills_sdk.models.registry import (
    RegistryIdentity,
    RegistryPreparationBlocker,
    RegistryPreparationReceipt,
    RegistryPreparationRequest,
)
from skills_sdk.packaging import harden_skill_package

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "package-receipts"


def _package_receipt() -> PackageReceiptV2:
    return PackageReceiptV2.model_validate(json.loads((FIXTURE_ROOT / "accepted-v2.json").read_text(encoding="utf-8")))


def _registry_receipt(package_receipt: PackageReceiptV2) -> RegistryPreparationReceipt:
    return prepare_private_registry_candidate(
        package_receipt,
        harden_skill_package(package_receipt),
        RegistryPreparationRequest(
            registry=RegistryIdentity(registry_id="private-registry", namespace="team"),
            package_name="synthetic-skill",
            version="0.1.0",
            evidence=("evidence/private-registry-preparation.json",),
        ),
    )


def _plan(package_receipt: PackageReceiptV2, registry_receipt: RegistryPreparationReceipt, lock: RuntimeLock):
    return plan_runtime_install(
        package_receipt,
        registry_receipt,
        lock,
        RuntimeTarget(scope="project", target_id="project-runtime"),
        evidence=("evidence/install-plan.json",),
    )


def test_install_plan_is_deterministic_bound_and_non_mutating() -> None:
    package_receipt = _package_receipt()
    registry_receipt = _registry_receipt(package_receipt)
    first = _plan(package_receipt, registry_receipt, RuntimeLock())
    second = _plan(package_receipt, registry_receipt, RuntimeLock())
    assert first == second
    assert first.status == "planned"
    assert first.operation == "install"
    assert first.candidate == package_receipt.candidate
    assert first.package_digest == package_receipt.package_digest
    assert first.package_receipt_id == package_receipt.receipt_id
    assert first.registry_input_receipt_id == package_receipt.receipt_id
    assert first.rollback_lock_sha256 == first.current_lock_sha256
    assert first.mutation_performed is False


def test_install_plan_preserves_entry_order_and_reports_no_change() -> None:
    package_receipt = _package_receipt()
    registry_receipt = _registry_receipt(package_receipt)
    initial = _plan(package_receipt, registry_receipt, RuntimeLock())
    assert initial.proposed_entry is not None
    other_candidate = PackageCandidateIdentity(
        package_id="other-skill", source_revision="4" * 40, content_sha256="e" * 64
    )
    other_entry = initial.proposed_entry.model_copy(
        update={"package_name": "other-skill", "candidate": other_candidate}
    )
    repeated = _plan(package_receipt, registry_receipt, RuntimeLock(entries=(other_entry, initial.proposed_entry)))
    assert repeated.operation == "no_change"
    assert repeated.current_lock_sha256 == repeated.proposed_lock_sha256
    assert repeated.proposed_entry == initial.proposed_entry


def test_unrelated_registry_input_receipt_is_a_typed_blocker() -> None:
    package_receipt = _package_receipt()
    registry_receipt = _registry_receipt(package_receipt).model_copy(
        update={"input_receipt_id": "package-receipt-unrelated"}
    )
    plan = _plan(package_receipt, registry_receipt, RuntimeLock())
    assert plan.status == "blocked"
    assert plan.blocker is not None
    assert plan.blocker.code == "installation_input_receipt_mismatch"
    assert plan.registry_input_receipt_id == "package-receipt-unrelated"
    assert plan.proposed_lock_sha256 is None


def test_registry_blocker_with_unsafe_code_is_replaced_by_portable_blocker() -> None:
    package_receipt = _package_receipt()
    unsafe_blocker = RegistryPreparationBlocker(
        code="to" + "ken=plainvalue",
        message="Blocked by policy",
    )
    registry_receipt = _registry_receipt(package_receipt).model_copy(
        update={
            "status": "blocked",
            "candidate": None,
            "package_digest": None,
            "manifest_digest": None,
            "hardening_receipt_sha256": None,
            "blocker": unsafe_blocker,
            "blockers": (unsafe_blocker,),
        }
    )
    plan = _plan(package_receipt, registry_receipt, RuntimeLock())
    assert plan.status == "blocked"
    assert plan.blocker is not None
    assert plan.blocker.code == "installation_registry_blocker_not_portable"


def test_planner_has_no_host_or_external_dependencies() -> None:
    source = (Path(__file__).parents[1] / "src/skills_sdk/lifecycle/planning.py").read_text(encoding="utf-8")
    for forbidden in ("pathlib", "open(", "write_text", "subprocess", "requests", "httpx", "socket"):
        assert forbidden not in source
