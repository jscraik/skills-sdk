"""Whole-plugin supplied safety assessment bound to a complete captured candidate."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    field_validator,
    model_validator,
)
from pydantic_core import TzInfo

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.inventory import _ContractModel
from skills_sdk.models.packaging import PackageFileRole
from skills_sdk.models.plugin import _PLUGIN_MODELS, PluginPackageValidation
from skills_sdk.models.pre_execution_safety import SAFETY_CHECK_IDS, CapabilitySafetyReview
from skills_sdk.models.risk import SecurityFinding, SecurityScreeningResult
from skills_sdk.models.safety import PackageSafetyEvidenceReference, PackageSafetyReviewer
from skills_sdk.models.validation import ValidationSeverity

_PLUGIN_SAFETY_MODELS = frozenset(
    {
        *_PLUGIN_MODELS,
        PluginPackageValidation,
        CapabilitySafetyReview,
        SecurityFinding,
        SecurityScreeningResult,
        PackageSafetyEvidenceReference,
        PackageSafetyReviewer,
    }
)


def _canonical_input(value: object, root_model: type[BaseModel], *, work_limit: int) -> object:
    """Copy bounded canonical SDK models without invoking caller serializers."""
    allowed = (*_PLUGIN_SAFETY_MODELS, root_model)
    remaining = work_limit
    active: set[int] = set()

    def visit(item: object, depth: int) -> object:
        nonlocal remaining
        kind = type(item)
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise ValueError("plugin safety evidence exceeds its work or nesting bound")
        if item is None or any(kind is scalar for scalar in (str, bool, int, float)):
            return item
        if kind is datetime:
            if type(item.tzinfo) not in (type(None), timezone, TzInfo):
                raise ValueError("plugin safety timestamp requires a canonical fixed timezone")
            return datetime.isoformat(item)
        if kind is PackageFileRole or kind is ValidationSeverity:
            return item.value
        if not any(kind is canonical for canonical in (*allowed, dict, list, tuple)):
            raise ValueError("plugin safety evidence requires canonical models, containers and JSON scalars")
        identity = id(item)
        if identity in active:
            raise ValueError("plugin safety evidence must not contain cycles")
        active.add(identity)
        try:
            if any(kind is model for model in allowed):
                fields = object.__getattribute__(item, "__dict__")
                extras = object.__getattribute__(item, "__pydantic_extra__")
                if type(fields) is not dict or (extras is not None and type(extras) is not dict):
                    raise ValueError("plugin safety model storage requires canonical dictionaries")
                if len(fields) > remaining or any(type(key) is not str for key in fields):
                    raise ValueError("plugin safety model storage exceeds its bounded exact keys")
                if any(key not in kind.model_fields for key in fields) or extras:
                    raise ValueError("copied plugin safety evidence contains unknown members")
                return visit(fields, depth + 1)
            if len(item) > remaining:
                raise ValueError("plugin safety evidence exceeds its work boundary")
            if kind is dict:
                if any(type(key) is not str for key in item):
                    raise ValueError("plugin safety evidence requires exact string keys")
                false_fields = {"mutation_performed", "review_authenticity_verified", "promotion_authorized"}
                if any(key in item and item[key] is not False for key in false_fields):
                    raise ValueError("plugin safety evidence cannot coerce false-only authority fields")
                return {key: visit(member, depth + 1) for key, member in item.items()}
            return [visit(member, depth + 1) for member in item]
        finally:
            active.remove(identity)

    return visit(value, 0)


def _required_checks(value: PluginPreExecutionSafetyEvidence) -> set[str]:
    """Derive applicable review categories from complete plugin findings and files."""
    required = {"content_and_injection", "secrets_and_privacy"}
    categories = {finding.category for finding in value.screening.findings}
    codes = {finding.code for finding in value.screening.findings}
    if "external_service" in categories:
        required.add("network_and_external_writes")
    if "dependency" in categories:
        required.add("dependencies_and_binaries")
    if "unsafe_path" in categories or codes & {"executable_source_capability", "pipe_to_shell_download"}:
        required.add("filesystem_and_subprocess")
    if "mcp_auth" in categories or "system_service_modification" in codes:
        required.add("tools_and_privileges")
    paths = {item.path for item in value.validation.files}
    if any(path == "mcp.json" or path.endswith("/mcp.json") for path in paths):
        required.add("tools_and_privileges")
    if any(
        item.permission_mode & 0o111 or "scripts" in item.path.split("/")[:-1]
        for item in value.validation.files
    ):
        required |= {"filesystem_and_subprocess", "dependencies_and_binaries"}
    return required


class PluginPreExecutionSafetyEvidence(_ContractModel):
    """Supplied no-issue assessment; it is neither executed nor authenticated review."""

    schema_version: Literal["plugin-pre-execution-safety-evidence/v1"] = "plugin-pre-execution-safety-evidence/v1"
    status: Literal["assessed_no_issue"] = "assessed_no_issue"
    validation: PluginPackageValidation
    screening: SecurityScreeningResult
    checklist_version: Literal["sdk-capability-checklist/v1"] = "sdk-capability-checklist/v1"
    checklist: tuple[CapabilitySafetyReview, ...]
    reviewer: PackageSafetyReviewer
    observed_at: AwareDatetime
    evidence: tuple[PackageSafetyEvidenceReference, ...] = Field(min_length=3, max_length=128)
    mutation_performed: Literal[False] = False
    review_authenticity_verified: Literal[False] = False
    promotion_authorized: Literal[False] = False

    _ingress_work_limit: ClassVar[int] = 524288
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="wrap")
    @classmethod
    def canonical_nested_input(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        """Reject copied, constructed, cyclic and coercible nested evidence."""
        return handler(_canonical_input(value, cls, work_limit=cls._ingress_work_limit))

    @field_validator("mutation_performed", "review_authenticity_verified", "promotion_authorized", mode="before")
    @classmethod
    def false_only(cls, value: object) -> object:
        """Reject integer and truthy substitutes for non-authority flags."""
        if value is not False:
            raise ValueError("plugin safety evidence cannot claim mutation, authenticity or promotion")
        return value

    @field_validator("observed_at", mode="before")
    @classmethod
    def aware_timestamp_string(cls, value: object) -> object:
        """Accept only caller-supplied RFC3339-shaped strings at raw ingress."""
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("plugin safety observed_at requires an aware RFC3339 string")
            return value
        if type(value) is not str or "T" not in value.upper():
            raise ValueError("plugin safety observed_at requires an aware RFC3339 string")
        return value

    @model_validator(mode="after")
    def complete_capture_is_assessed(self) -> Self:
        """Bind screening, review evidence and applicable checks to the complete plugin."""
        candidate = self.validation.candidate
        if self.validation.status != "pass" or candidate is None or self.validation.mode_manifest_sha256 is None:
            raise ValueError("plugin safety evidence requires passing complete plugin validation")
        paths = tuple(item.path for item in self.validation.files)
        finding_paths = {path for finding in self.screening.findings for path in finding.evidence_refs}
        if (
            self.screening.candidate != candidate
            or self.screening.sensor_ids != ("sdk-static-signature-v1",)
            or self.screening.status == "blocked"
            or self.screening.scanned_paths != paths
            or not finding_paths <= set(paths)
        ):
            raise ValueError("plugin safety screening must bind every captured path and finding")
        if self.reviewer.method == "metadata":
            raise ValueError("plugin safety requires a substantive supplied review method")
        self._check_evidence()
        self._check_checklist()
        return self

    def _check_evidence(self) -> None:
        """Require unique references and the three canonical binding digests."""
        ids = tuple(item.evidence_id for item in self.evidence)
        refs = tuple(item.ref for item in self.evidence)
        if len(ids) != len(set(ids)) or len(refs) != len(set(refs)):
            raise ValueError("plugin safety evidence identifiers and references must be unique")
        by_id = {item.evidence_id: item.sha256 for item in self.evidence}
        expected = {
            "plugin-capture": canonical_json_sha256(self.validation.model_dump(mode="json")),
            "static-screening": canonical_json_sha256(self.screening.model_dump(mode="json")),
            "capability-checklist": canonical_json_sha256(
                {
                    "version": self.checklist_version,
                    "checks": [item.model_dump(mode="json") for item in self.checklist],
                }
            ),
        }
        if any(by_id.get(evidence_id) != digest for evidence_id, digest in expected.items()):
            raise ValueError("plugin safety evidence digests must bind capture, screening and checklist")

    def _check_checklist(self) -> None:
        """Require canonical ordered checks and no-issue decisions where applicable."""
        if tuple(item.check_id for item in self.checklist) != SAFETY_CHECK_IDS:
            raise ValueError("plugin safety checklist requires every canonical check in order")
        known_ids = {item.evidence_id for item in self.evidence}
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        for item in self.checklist:
            if not set(item.evidence_ids) <= known_ids:
                raise ValueError("plugin safety checklist must reference supplied evidence")
            if item.check_id in _required_checks(self) and (
                item.status != "reviewed_no_issue"
                or not any(
                    evidence_by_id[evidence_id].kind == self.reviewer.method for evidence_id in item.evidence_ids
                )
            ):
                raise ValueError("applicable checks require substantive matching review evidence")


__all__ = ["PluginPreExecutionSafetyEvidence"]
