"""Portable actual-artifact input for the pre-execution safety binding check."""

from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ModelWrapValidatorHandler, field_validator, model_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.inventory import NonEmptyText, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import (
    PackageManifest,
    PackageManifestFile,
    PackageManifestProvenance,
    PackageReceiptBlocker,
    PackageReceiptV2,
)
from skills_sdk.models.risk import SecurityFinding, SecurityScreeningResult
from skills_sdk.models.safety import (
    PackageSafetyBlocker,
    PackageSafetyEvidenceReceipt,
    PackageSafetyEvidenceReference,
    PackageSafetyFinding,
    PackageSafetyReviewer,
    SafetyEvidenceId,
    _public_text_is_redaction_safe,
)

SafetyCheckId = Literal[
    "content_and_injection",
    "secrets_and_privacy",
    "filesystem_and_subprocess",
    "network_and_external_writes",
    "dependencies_and_binaries",
    "tools_and_privileges",
]
SAFETY_CHECK_IDS = (
    "content_and_injection",
    "secrets_and_privacy",
    "filesystem_and_subprocess",
    "network_and_external_writes",
    "dependencies_and_binaries",
    "tools_and_privileges",
)


class CapabilitySafetyReview(_ContractModel):
    """One explicit review outcome or explained non-applicability decision."""

    model_config = ConfigDict(revalidate_instances="always")

    check_id: SafetyCheckId
    status: Literal["reviewed_no_issue", "not_applicable"]
    rationale: NonEmptyText
    evidence_ids: tuple[SafetyEvidenceId, ...] = Field(min_length=1)

    @model_validator(mode="wrap")
    @classmethod
    def copied_models_must_be_revalidated(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        return handler(_canonical_nested_input(value))

    @field_validator("rationale")
    @classmethod
    def rationale_must_be_public(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("checklist rationale must not be blank")
        if not _public_text_is_redaction_safe(value):
            raise ValueError("checklist rationale must not contain private values")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_must_be_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("checklist evidence ids must be unique")
        return values


class PreExecutionSafetyEvidence(_ContractModel):
    """Actual upstream and review artifacts, never an ID-only admission flag."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["pre-execution-safety-evidence/v1"] = "pre-execution-safety-evidence/v1"
    package_receipt: PackageReceiptV2
    safety_receipt: PackageSafetyEvidenceReceipt
    screening: SecurityScreeningResult
    checklist_version: Literal["sdk-capability-checklist/v1"] = "sdk-capability-checklist/v1"
    checklist: tuple[CapabilitySafetyReview, ...]

    @model_validator(mode="wrap")
    @classmethod
    def actual_artifacts_must_be_revalidated(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        return handler(_canonical_nested_input(value))

    @model_validator(mode="after")
    def upstream_and_review_must_bind(self) -> "PreExecutionSafetyEvidence":
        self.safety_receipt.validate_against_package_receipt(self.package_receipt)
        if self.package_receipt.manifest is None or self.screening.candidate != self.package_receipt.candidate:
            raise ValueError("screening must bind the built package")
        if self.screening.scanned_paths != tuple(item.path for item in self.package_receipt.manifest.files):
            raise ValueError("screening must capture every manifested file in order")
        if self.screening.sensor_ids != ("sdk-static-signature-v1",) or self.screening.status == "blocked":
            raise ValueError("execution requires the supported completed static screening")
        self._check_review_bindings()
        return self

    def _check_review_bindings(self) -> None:
        if tuple(item.check_id for item in self.checklist) != SAFETY_CHECK_IDS:
            raise ValueError("checklist must contain each canonical check exactly once in order")
        evidence = {item.evidence_id: item for item in self.safety_receipt.evidence}
        bindings = {
            "static-screening": canonical_json_sha256(self.screening.model_dump(mode="json")),
            "capability-checklist": canonical_json_sha256(
                {
                    "version": self.checklist_version,
                    "checks": [item.model_dump(mode="json") for item in self.checklist],
                }
            ),
        }
        if any(key not in evidence or evidence[key].sha256 != digest for key, digest in bindings.items()):
            raise ValueError("safety review must retain the actual screening and checklist digests")
        required = _required_checks(self)
        for item in self.checklist:
            if not set(item.evidence_ids) <= evidence.keys():
                raise ValueError("each checklist outcome must retain supplied review evidence")
            if item.check_id in required and item.status != "reviewed_no_issue":
                raise ValueError("applicable checks cannot be marked not applicable")


def _required_checks(value: PreExecutionSafetyEvidence) -> set[str]:
    required = {"content_and_injection", "secrets_and_privacy"}
    categories = {finding.category for finding in value.screening.findings}
    if "external_service" in categories:
        required.add("network_and_external_writes")
    if "dependency" in categories:
        required.add("dependencies_and_binaries")
    if "unsafe_path" in categories or any(
        f.code in {"executable_source_capability", "pipe_to_shell_download"} for f in value.screening.findings
    ):
        required.add("filesystem_and_subprocess")
    if "mcp_auth" in categories or any(f.code == "system_service_modification" for f in value.screening.findings):
        required.add("tools_and_privileges")
    assert value.package_receipt.manifest is not None
    if any(item.role == "script" for item in value.package_receipt.manifest.files):
        required.update({"filesystem_and_subprocess", "dependencies_and_binaries"})
    return required


_CANONICAL_EVIDENCE_MODELS = frozenset(
    {
        CapabilitySafetyReview,
        PreExecutionSafetyEvidence,
        PackageCandidateIdentity,
        PackageManifest,
        PackageManifestFile,
        PackageManifestProvenance,
        PackageReceiptBlocker,
        PackageReceiptV2,
        PackageSafetyBlocker,
        PackageSafetyEvidenceReceipt,
        PackageSafetyEvidenceReference,
        PackageSafetyFinding,
        PackageSafetyReviewer,
        SecurityFinding,
        SecurityScreeningResult,
    }
)


def _canonical_nested_input(value: object) -> object:
    """Bound mixed nested inputs without dropping copied fields or validators."""
    remaining = 131072
    active: set[int] = set()

    def visit(item: object, depth: int) -> object:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise ValueError("pre-execution evidence exceeds its work or nesting bound")
        if isinstance(item, (bytes, bytearray, memoryview)):
            raise ValueError("pre-execution evidence must not coerce byte strings")
        if not isinstance(item, (BaseModel, Mapping, list, tuple)):
            return item
        identity = id(item)
        if identity in active:
            raise ValueError("pre-execution evidence must not contain cycles")
        active.add(identity)
        try:
            if isinstance(item, BaseModel):
                if type(item) not in _CANONICAL_EVIDENCE_MODELS:
                    raise ValueError("pre-execution evidence requires canonical SDK model classes")
                if set(item.__dict__) - set(type(item).model_fields) or item.__pydantic_extra__:
                    raise ValueError("copied pre-execution evidence contains unknown members")
                # Audit raw members before serialization can hide copied fields
                # or coerce bytes, then retain the contract's JSON scalar forms.
                visit(item.__dict__, depth + 1)
                return visit(item.model_dump(mode="json"), depth + 1)
            if isinstance(item, Mapping):
                if any(type(key) is not str for key in item):
                    raise ValueError("pre-execution evidence requires string dictionary keys")
                if "mutation_performed" in item and item["mutation_performed"] is not False:
                    raise ValueError("pre-execution evidence cannot coerce mutation constants")
                return {key: visit(member, depth + 1) for key, member in item.items()}
            return [visit(member, depth + 1) for member in item]
        finally:
            active.remove(identity)

    return visit(value, 0)
