"""Deterministic runtime-lock planning over immutable package evidence."""

from __future__ import annotations

from typing import Literal

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.lifecycle import (
    InstallPlan,
    RuntimeFile,
    RuntimeLock,
    RuntimeLockEntry,
    RuntimeTarget,
    lifecycle_text_is_public_safe,
)
from skills_sdk.models.packaging import PackageReceiptV2
from skills_sdk.models.registry import RegistryPreparationBlocker, RegistryPreparationReceipt


def _lock_digest(lock: RuntimeLock) -> str:
    return canonical_json_sha256(lock.model_dump(mode="json"))


def _plan_id(payload: object) -> str:
    return f"install-plan-{canonical_json_sha256(payload)[:24]}"


def _blocker(code: str, message: str) -> RegistryPreparationBlocker:
    return RegistryPreparationBlocker(code=code, message=message)


def _blocked_plan(
    package_receipt: PackageReceiptV2,
    registry_receipt: RegistryPreparationReceipt,
    current_lock: RuntimeLock,
    target: RuntimeTarget,
    evidence: tuple[str, ...],
    blocker: RegistryPreparationBlocker,
) -> InstallPlan:
    current_digest = _lock_digest(current_lock)
    candidate = package_receipt.candidate
    package_name = candidate.package_id if candidate is not None else registry_receipt.package_name
    version = package_receipt.manifest.version if package_receipt.manifest is not None else registry_receipt.version
    package_digest = package_receipt.package_digest if package_receipt.status == "built" else None
    identity = {
        "candidate": candidate.model_dump(mode="json") if candidate else None,
        "package_name": package_name,
        "version": version,
        "package_digest": package_digest,
        "package_receipt_id": package_receipt.receipt_id,
        "registry": registry_receipt.registry.model_dump(mode="json"),
        "registry_preparation_receipt_id": registry_receipt.receipt_id,
        "registry_input_receipt_id": registry_receipt.input_receipt_id,
        "current_lock_sha256": current_digest,
        "rollback_lock_sha256": current_digest,
        "target": target.model_dump(mode="json"),
        "status": "blocked",
        "evidence": evidence,
        "blocker": blocker.model_dump(mode="json"),
    }
    return InstallPlan(
        plan_id=_plan_id(identity),
        candidate=candidate,
        package_name=package_name,
        version=version,
        package_digest=package_digest,
        package_receipt_id=package_receipt.receipt_id,
        status="blocked",
        target=target,
        registry=registry_receipt.registry,
        registry_preparation_receipt_id=registry_receipt.receipt_id,
        registry_input_receipt_id=registry_receipt.input_receipt_id,
        current_lock_sha256=current_digest,
        rollback_lock_sha256=current_digest,
        evidence=evidence,
        blocker=blocker,
    )


def _identity_blocker(
    package_receipt: PackageReceiptV2,
    registry_receipt: RegistryPreparationReceipt,
) -> RegistryPreparationBlocker | None:
    if registry_receipt.input_receipt_id != package_receipt.receipt_id:
        return _blocker(
            "installation_input_receipt_mismatch",
            "Registry preparation must identify the exact package receipt used for planning.",
        )
    if registry_receipt.status == "blocked":
        assert registry_receipt.blocker is not None
        if (
            not lifecycle_text_is_public_safe(registry_receipt.blocker.code)
            or not lifecycle_text_is_public_safe(registry_receipt.blocker.message)
            or any(not lifecycle_text_is_public_safe(ref) for ref in registry_receipt.blocker.evidence_refs)
        ):
            return _blocker(
                "installation_registry_blocker_not_portable",
                "Registry preparation blocker cannot be projected into a portable install plan.",
            )
        return registry_receipt.blocker
    if (
        package_receipt.status != "built"
        or package_receipt.candidate != registry_receipt.candidate
        or package_receipt.package_digest != registry_receipt.package_digest
    ):
        return _blocker(
            "installation_identity_mismatch",
            "Package and registry preparation must bind the same built candidate and digest.",
        )
    if package_receipt.manifest is None or package_receipt.manifest.version != registry_receipt.version:
        return _blocker(
            "installation_version_mismatch",
            "Package manifest and registry preparation must bind the same version.",
        )
    return None


def plan_runtime_install(
    package_receipt: PackageReceiptV2,
    registry_receipt: RegistryPreparationReceipt,
    current_lock: RuntimeLock,
    target: RuntimeTarget,
    *,
    evidence: tuple[str, ...],
) -> InstallPlan:
    """Return an intended lock transition without inspecting or mutating a runtime."""

    package_receipt = PackageReceiptV2.model_validate(package_receipt.model_dump(mode="json"))
    registry_receipt = RegistryPreparationReceipt.model_validate(registry_receipt.model_dump(mode="json"))
    current_lock = RuntimeLock.model_validate(current_lock.model_dump(mode="json"))
    target = RuntimeTarget.model_validate(target.model_dump(mode="json"))
    blocker = _identity_blocker(package_receipt, registry_receipt)
    if blocker is not None:
        return _blocked_plan(package_receipt, registry_receipt, current_lock, target, evidence, blocker)
    return _planned_transition(package_receipt, registry_receipt, current_lock, target, evidence)


def _planned_transition(
    package_receipt: PackageReceiptV2,
    registry_receipt: RegistryPreparationReceipt,
    current_lock: RuntimeLock,
    target: RuntimeTarget,
    evidence: tuple[str, ...],
) -> InstallPlan:
    assert package_receipt.candidate is not None
    assert package_receipt.manifest is not None
    assert package_receipt.package_digest is not None
    entry = RuntimeLockEntry(
        package_name=registry_receipt.package_name,
        version=registry_receipt.version,
        candidate=package_receipt.candidate,
        package_digest=package_receipt.package_digest,
        registry=registry_receipt.registry,
        package_receipt_id=package_receipt.receipt_id,
        registry_preparation_receipt_id=registry_receipt.receipt_id,
        target=target,
        files=tuple(RuntimeFile(path=item.path, sha256=item.sha256) for item in package_receipt.manifest.files),
    )
    key = _entry_key(entry)
    matching = tuple(item for item in current_lock.entries if _entry_key(item) == key)
    operation: Literal["install", "update", "no_change"]
    operation = "no_change" if matching == (entry,) else "update" if matching else "install"
    proposed_entries = tuple(entry if _entry_key(item) == key else item for item in current_lock.entries)
    if not matching:
        proposed_entries = (*proposed_entries, entry)
    proposed_lock = RuntimeLock(entries=proposed_entries)
    current_digest = _lock_digest(current_lock)
    proposed_digest = _lock_digest(proposed_lock)
    identity = {
        "candidate": package_receipt.candidate.model_dump(mode="json"),
        "package_name": registry_receipt.package_name,
        "version": registry_receipt.version,
        "package_digest": package_receipt.package_digest,
        "package_receipt_id": package_receipt.receipt_id,
        "registry": registry_receipt.registry.model_dump(mode="json"),
        "registry_preparation_receipt_id": registry_receipt.receipt_id,
        "registry_input_receipt_id": registry_receipt.input_receipt_id,
        "current_lock_sha256": current_digest,
        "rollback_lock_sha256": current_digest,
        "proposed_lock_sha256": proposed_digest,
        "target": target.model_dump(mode="json"),
        "status": "planned",
        "operation": operation,
        "proposed_entry": entry.model_dump(mode="json"),
        "evidence": evidence,
    }
    return InstallPlan(
        plan_id=_plan_id(identity),
        candidate=package_receipt.candidate,
        package_name=registry_receipt.package_name,
        version=registry_receipt.version,
        package_digest=package_receipt.package_digest,
        package_receipt_id=package_receipt.receipt_id,
        status="planned",
        operation=operation,
        target=target,
        registry=registry_receipt.registry,
        registry_preparation_receipt_id=registry_receipt.receipt_id,
        registry_input_receipt_id=registry_receipt.input_receipt_id,
        current_lock_sha256=current_digest,
        rollback_lock_sha256=current_digest,
        proposed_lock_sha256=proposed_digest,
        proposed_entry=entry,
        evidence=evidence,
    )


def _entry_key(entry: RuntimeLockEntry) -> tuple[str, str, str]:
    return (entry.target.scope, entry.target.target_id, entry.package_name)


__all__ = ["plan_runtime_install"]
