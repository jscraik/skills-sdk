"""Deterministic private-registry preparation over immutable receipts."""

from __future__ import annotations

import re

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.packaging import (
    PackageHardeningReceipt,
    PackageReceiptBlocker,
    PackageReceiptV2,
)
from skills_sdk.models.registry import (
    REGISTRY_PACKAGE_NAME_MAX_LENGTH,
    REGISTRY_VERSION_PATTERN,
    RegistryPreparationBlocker,
    RegistryPreparationReceipt,
    RegistryPreparationRequest,
    RegistryPreparationWarning,
    registry_evidence_is_redaction_safe,
)


def _receipt_id(payload: object) -> str:
    return f"registry-preparation-{canonical_json_sha256(payload)[:24]}"


def _blocked_receipt(
    package_receipt: PackageReceiptV2,
    hardening_receipt: PackageHardeningReceipt,
    request: RegistryPreparationRequest,
    blocker: RegistryPreparationBlocker,
    blockers: tuple[RegistryPreparationBlocker, ...] | None = None,
    warnings: tuple[RegistryPreparationWarning, ...] = (),
) -> RegistryPreparationReceipt:
    retained_blockers = blockers or (blocker,)
    identity_payload = {
        "candidate": package_receipt.candidate.model_dump(mode="json")
        if package_receipt.candidate is not None
        else None,
        "request": request.model_dump(mode="json"),
        "input_receipt_id": package_receipt.receipt_id,
        "hardening_receipt_sha256": canonical_json_sha256(hardening_receipt.model_dump(mode="json")),
        "blocker": blocker.model_dump(mode="json"),
        "blockers": [item.model_dump(mode="json") for item in retained_blockers],
        "warnings": [warning.model_dump(mode="json") for warning in warnings],
    }
    return RegistryPreparationReceipt(
        receipt_id=_receipt_id(identity_payload),
        candidate=package_receipt.candidate,
        registry=request.registry,
        package_name=request.package_name,
        version=request.version,
        input_receipt_id=package_receipt.receipt_id,
        status="blocked",
        evidence=request.evidence,
        blocker=blocker,
        blockers=retained_blockers,
        warnings=warnings,
    )


def _split_evidence(values: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    refs: list[str] = []
    source_digests: list[str] = []
    for value in values:
        if not registry_evidence_is_redaction_safe(value):
            digest = canonical_json_sha256(value)
            if digest not in source_digests:
                source_digests.append(digest)
            continue
        try:
            require_portable_relative_path(value)
        except ContractError:
            digest = canonical_json_sha256(value)
            if digest not in source_digests:
                source_digests.append(digest)
        else:
            if value not in refs:
                refs.append(value)
    return tuple(refs), tuple(source_digests)


def _registry_blocker(blocker: PackageReceiptBlocker) -> RegistryPreparationBlocker:
    evidence_refs, source_evidence_sha256 = _split_evidence(blocker.evidence_refs)
    public_text_safe = registry_evidence_is_redaction_safe(blocker.code) and registry_evidence_is_redaction_safe(
        blocker.message
    )
    return RegistryPreparationBlocker(
        code=blocker.code if public_text_safe else "source_blocker_redacted",
        message=blocker.message
        if public_text_safe
        else "Source blocker metadata was redacted; use its digest for identity.",
        evidence_refs=evidence_refs,
        source_evidence_sha256=source_evidence_sha256,
        source_blocker_sha256=canonical_json_sha256(blocker.model_dump(mode="json")),
    )


def _hardening_blockers(hardening_receipt: PackageHardeningReceipt) -> tuple[RegistryPreparationBlocker, ...]:
    retained: list[RegistryPreparationBlocker] = []
    for item in hardening_receipt.blockers:
        evidence_refs, source_evidence_sha256 = _split_evidence(item.evidence)
        public_text_safe = registry_evidence_is_redaction_safe(item.id) and registry_evidence_is_redaction_safe(
            item.message
        )
        retained.append(
            RegistryPreparationBlocker(
                code=item.id if public_text_safe else "source_blocker_redacted",
                message=item.message
                if public_text_safe
                else "Source blocker metadata was redacted; use its digest for identity.",
                evidence_refs=evidence_refs,
                source_evidence_sha256=source_evidence_sha256,
                source_blocker_sha256=canonical_json_sha256(item.model_dump(mode="json")),
            )
        )
    return tuple(retained)


def _registry_warnings(hardening_receipt: PackageHardeningReceipt) -> tuple[RegistryPreparationWarning, ...]:
    projected: list[RegistryPreparationWarning] = []
    for warning in hardening_receipt.warnings:
        evidence_refs, source_evidence_sha256 = _split_evidence(warning.evidence)
        projected.append(
            RegistryPreparationWarning(
                warning_sha256=canonical_json_sha256(warning.model_dump(mode="json")),
                evidence_refs=evidence_refs,
                source_evidence_sha256=source_evidence_sha256,
            )
        )
    return tuple(projected)


def _input_blockers(
    package_receipt: PackageReceiptV2,
    hardening_receipt: PackageHardeningReceipt,
    request: RegistryPreparationRequest,
) -> tuple[RegistryPreparationBlocker, ...]:
    if package_receipt.status == "blocked":
        return (
            _registry_blocker(package_receipt.blocker)
            if package_receipt.blocker is not None
            else RegistryPreparationBlocker(
                code="package_receipt_blocked",
                message="Private-registry preparation requires a built package receipt.",
            ),
        )
    if (
        hardening_receipt.candidate != package_receipt.candidate
        or hardening_receipt.package_digest != package_receipt.package_digest
    ):
        return (
            RegistryPreparationBlocker(
                code="hardening_identity_mismatch",
                message="Package and hardening receipts must bind the same candidate and package digest.",
            ),
        )
    assert package_receipt.manifest is not None
    if request.version != package_receipt.manifest.version:
        return (
            RegistryPreparationBlocker(
                code="package_version_mismatch",
                message="Registry version must match the immutable package manifest version.",
            ),
        )
    if hardening_receipt.status == "blocked":
        return _hardening_blockers(hardening_receipt)
    assert package_receipt.candidate is not None
    if request.package_name != package_receipt.candidate.package_id:
        return (
            RegistryPreparationBlocker(
                code="package_name_mismatch",
                message="Registry package name must match the immutable candidate package_id.",
            ),
        )
    if len(request.package_name) > REGISTRY_PACKAGE_NAME_MAX_LENGTH:
        return (
            RegistryPreparationBlocker(
                code="registry_package_name_unsupported",
                message="Registry package name exceeds the supported length limit.",
            ),
        )
    if re.fullmatch(REGISTRY_VERSION_PATTERN, request.version) is None:
        return (
            RegistryPreparationBlocker(
                code="registry_version_unsupported",
                message="Registry version must use canonical Semantic Versioning.",
            ),
        )
    return ()


def _prepared_receipt(
    package_receipt: PackageReceiptV2,
    hardening_receipt: PackageHardeningReceipt,
    request: RegistryPreparationRequest,
) -> RegistryPreparationReceipt:
    assert package_receipt.candidate is not None
    assert package_receipt.manifest is not None
    assert package_receipt.package_digest is not None
    manifest_digest = canonical_json_sha256(package_receipt.manifest.model_dump(mode="json"))
    hardening_digest = canonical_json_sha256(hardening_receipt.model_dump(mode="json"))
    warnings = _registry_warnings(hardening_receipt)
    identity_payload = {
        "candidate": package_receipt.candidate.model_dump(mode="json"),
        "request": request.model_dump(mode="json"),
        "input_receipt_id": package_receipt.receipt_id,
        "package_digest": package_receipt.package_digest,
        "manifest_digest": manifest_digest,
        "hardening_receipt_sha256": hardening_digest,
        "warnings": [warning.model_dump(mode="json") for warning in warnings],
    }
    return RegistryPreparationReceipt(
        receipt_id=_receipt_id(identity_payload),
        candidate=package_receipt.candidate,
        registry=request.registry,
        package_name=request.package_name,
        version=request.version,
        input_receipt_id=package_receipt.receipt_id,
        package_digest=package_receipt.package_digest,
        manifest_digest=manifest_digest,
        hardening_receipt_sha256=hardening_digest,
        status="prepared",
        evidence=request.evidence,
        warnings=warnings,
    )


def prepare_private_registry_candidate(
    package_receipt: PackageReceiptV2,
    hardening_receipt: PackageHardeningReceipt,
    request: RegistryPreparationRequest,
) -> RegistryPreparationReceipt:
    """Prepare a secret-free local registry receipt without network or filesystem mutation."""

    package_receipt = PackageReceiptV2.model_validate(package_receipt.model_dump(mode="json"))
    hardening_receipt = PackageHardeningReceipt.model_validate(hardening_receipt.model_dump(mode="json"))
    request = RegistryPreparationRequest.model_validate(request.model_dump(mode="json"))
    blockers = _input_blockers(package_receipt, hardening_receipt, request)
    if blockers:
        warnings = _registry_warnings(hardening_receipt) if package_receipt.status != "blocked" else ()
        if blockers[0].code == "hardening_identity_mismatch":
            warnings = ()
        return _blocked_receipt(
            package_receipt,
            hardening_receipt,
            request,
            blockers[0],
            blockers,
            warnings,
        )
    return _prepared_receipt(package_receipt, hardening_receipt, request)


__all__ = ["prepare_private_registry_candidate"]
