"""Secret-free envelopes for adapter-supplied provider execution evidence."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from pydantic_core import PydanticSerializationError

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import BlockerCode, ReceiptId
from skills_sdk.models.provider import ProviderIdentityV2

if TYPE_CHECKING:
    from skills_sdk.models.safety import PackageSafetyEvidenceReceipt

ExecutionId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")]
_MAX_PROVIDER_EXECUTION_INPUT_NESTING_DEPTH = 100
_CREDENTIAL_PATTERN = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----|"
    r"(?:^|[^A-Za-z0-9])(?:aiza|akia|bearer|ghp_|github_pat_|hf_|sk-|xoxb-|xoxp-|"
    r"(?:api[_-]?key|credential|password|private[_ -]?key|secret|token)[\"']?\s*[:=])",
    re.IGNORECASE,
)
_RFC3339_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")
_MACHINE_PATH_PATTERN = re.compile(
    r"(?:[fF][iI][lL][eE]:)?/+(?:[Uu][sS][eE][rR][sS]|[Hh][oO][mM][eE]|"
    r"[Pp][rR][iI][vV][aA][tT][eE]|[Tt][mM][pP]|[Ww][oO][rR][kK][sS][pP][aA][cC][eE]|"
    r"[Vv][aA][rR]/[Ff][oO][lL][dD][eE][rR][sS])/|"
    r"[A-Za-z]:[\\/]+(?:[Uu][sS][eE][rR][sS]|[Hh][oO][mM][eE])[\\/]|"
    r"(?:^|[\\/])(?:\$(?:\{)?(?:HOME|USER|USERPROFILE)(?:\})?|%(?:HOME|USER|USERPROFILE)%|"
    r"[Rr][Oo][Oo][Tt]|~)(?:[\\/]|$)",
    re.IGNORECASE,
)


def _identity_is_public(value: str) -> bool:
    return _CREDENTIAL_PATTERN.search(value) is None and _MACHINE_PATH_PATTERN.search(value) is None


def _candidate_is_public(candidate: PackageCandidateIdentity) -> bool:
    return _identity_is_public(candidate.package_id)


def _require_normalized_text(value: object, field_group: str) -> object:
    if isinstance(value, str) and value != value.strip():
        raise ValueError(f"provider execution {field_group} must already be normalized")
    return value


def _require_normalized_candidate(value: object) -> object:
    if isinstance(value, Mapping):
        for field in ("package_id", "source_revision", "content_sha256"):
            _require_normalized_text(value.get(field), "candidate identity fields")
    return value


def _normalize_json_input(
    value: object,
    active_container_ids: set[int] | None = None,
    depth: int = 0,
) -> object:
    if depth > _MAX_PROVIDER_EXECUTION_INPUT_NESTING_DEPTH:
        raise ValueError("provider execution input exceeds the maximum JSON nesting depth")
    if isinstance(value, BaseModel):
        try:
            serialized = value.model_dump(mode="json", warnings="error")
        except PydanticSerializationError as error:
            raise ValueError("provider execution nested model contains invalid field values") from error
        return _normalize_json_input(serialized, active_container_ids, depth + 1)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("provider execution input must not contain non-finite numbers")
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("provider execution input must contain only JSON-compatible values")
    if isinstance(value, Mapping | Sequence):
        active = active_container_ids if active_container_ids is not None else set()
        container_id = id(value)
        if container_id in active:
            raise ValueError("provider execution input must not contain cyclic containers")
        active.add(container_id)
        try:
            if isinstance(value, Mapping):
                if not all(isinstance(key, str) for key in value):
                    raise ValueError("provider execution input object keys must be strings")
                return {key: _normalize_json_input(item, active, depth + 1) for key, item in value.items()}
            return tuple(_normalize_json_input(item, active, depth + 1) for item in value)
        finally:
            active.remove(container_id)
    if isinstance(value, Iterable):
        raise ValueError("provider execution input must use JSON-compatible containers")
    raise ValueError("provider execution input must contain only JSON-compatible values")


class _ProviderExecutionContractModel(_ContractModel):
    model_config = ConfigDict(revalidate_instances="always")

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        **kwargs: Any,
    ) -> Self:
        """Revalidate exact model instances through their strict JSON representation."""

        if isinstance(obj, cls):
            obj = obj.model_dump(mode="json")
        return super().model_validate(obj, **kwargs)

    @model_validator(mode="before")
    @classmethod
    def public_input_must_be_json_compatible(cls, value: object) -> object:
        return _normalize_json_input(value)


class ProviderExecutionBlocker(_ProviderExecutionContractModel):
    """Typed, secret-free reason that execution could not proceed."""

    code: BlockerCode
    category: Literal["policy", "safety", "provider", "adapter", "transport", "input", "unknown"]
    evidence_refs: tuple[PortablePath, ...] = ()

    @field_validator("code", mode="before")
    @classmethod
    def code_must_be_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str):
            _require_normalized_text(value, "blocker code")
            if not _identity_is_public(value):
                raise ValueError("provider execution blocker code must not contain credential-shaped values")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("provider execution blocker evidence refs must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not _identity_is_public(value):
                raise ValueError("provider execution blocker evidence must not contain credential-shaped values")
        return values


class ProviderExecutionError(_ProviderExecutionContractModel):
    """Redacted adapter error classification with no raw provider response."""

    code: BlockerCode
    category: Literal["provider", "adapter", "transport", "timeout", "policy", "unknown"]
    retryable: bool
    evidence_refs: tuple[PortablePath, ...] = Field(min_length=1)

    @field_validator("retryable", mode="before")
    @classmethod
    def retryable_must_be_a_json_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("provider execution retryable must be a JSON boolean")
        return value

    @field_validator("code", mode="before")
    @classmethod
    def code_must_be_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str):
            _require_normalized_text(value, "error code")
            if not _identity_is_public(value):
                raise ValueError("provider execution error code must not contain credential-shaped values")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("provider execution error evidence refs must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not _identity_is_public(value):
                raise ValueError("provider execution error evidence must not contain credential-shaped values")
        return values


class ProviderUsageMetadata(_ProviderExecutionContractModel):
    """Optional adapter-reported unit counts; never a billing or cost claim."""

    unit_kind: Literal["tokens", "characters", "items", "provider_units"]
    input_units: int = Field(ge=0)
    output_units: int = Field(ge=0)
    total_units: int = Field(ge=0)

    @field_validator("input_units", "output_units", "total_units", mode="before")
    @classmethod
    def unit_counts_must_be_json_integers(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("provider usage counts must be JSON integers")
        return value

    @model_validator(mode="after")
    def total_matches_components(self) -> ProviderUsageMetadata:
        if self.total_units != self.input_units + self.output_units:
            raise ValueError("provider usage total must match input and output units")
        return self


class ProviderExecutionRequest(_ProviderExecutionContractModel):
    """Prepared provider request metadata; this model performs no execution."""

    schema_version: Literal["provider-execution-request/v1"] = "provider-execution-request/v1"
    request_id: ExecutionId
    candidate: PackageCandidateIdentity
    scenario_set_id: ExecutionId
    case_id: ExecutionId
    provider: ProviderIdentityV2
    declared_capability: Literal["response_generation", "agent_run", "embedding", "classification", "other"]
    input_sha256: Sha256
    idempotency_key_sha256: Sha256
    package_safety_receipt_id: ReceiptId
    package_safety_receipt_sha256: Sha256
    prepared_at: AwareDatetime
    status: Literal["prepared", "blocked"]
    blocker: ProviderExecutionBlocker | None = None
    evidence_refs: tuple[PortablePath, ...] = ()
    provider_execution_performed: Literal[False]
    credentials_included: Literal[False]
    raw_payloads_included: Literal[False]
    cost_claimed: Literal[False]

    @field_validator("prepared_at", mode="before")
    @classmethod
    def prepared_at_must_be_a_json_string(cls, value: object) -> object:
        if not isinstance(value, str) or _RFC3339_PATTERN.fullmatch(value) is None:
            raise ValueError("provider execution prepared_at must be an RFC3339 string")
        return value

    @field_validator("candidate", mode="before")
    @classmethod
    def candidate_identity_must_already_be_normalized(cls, value: object) -> object:
        return _require_normalized_candidate(value)

    @field_validator("request_id", "scenario_set_id", "case_id", "package_safety_receipt_id", mode="before")
    @classmethod
    def public_ids_must_be_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str):
            _require_normalized_text(value, "identity")
            if not _identity_is_public(value):
                raise ValueError("provider execution identity must not contain credential-shaped values")
        return value

    @field_validator("input_sha256", "idempotency_key_sha256", "package_safety_receipt_sha256", mode="before")
    @classmethod
    def digests_must_already_be_normalized(cls, value: object) -> object:
        return _require_normalized_text(value, "digest bindings")

    @field_validator(
        "provider_execution_performed",
        "credentials_included",
        "raw_payloads_included",
        "cost_claimed",
        mode="before",
    )
    @classmethod
    def false_only_fields_must_be_json_booleans(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("provider execution false-only fields must be JSON booleans")
        return value

    @field_validator("candidate")
    @classmethod
    def candidate_package_id_must_be_redaction_safe(
        cls, candidate: PackageCandidateIdentity
    ) -> PackageCandidateIdentity:
        if not _candidate_is_public(candidate):
            raise ValueError("provider execution candidate package id must not contain credential-shaped values")
        return candidate

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("provider execution request evidence refs must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not _identity_is_public(value):
                raise ValueError("provider execution request evidence must not contain credential-shaped values")
        return values

    @model_validator(mode="after")
    def status_matches_preparation(self) -> ProviderExecutionRequest:
        if self.status == "prepared" and self.blocker is not None:
            raise ValueError("prepared provider execution request cannot contain a blocker")
        if self.status == "blocked" and self.blocker is None:
            raise ValueError("blocked provider execution request requires a blocker")
        return self

    def validate_against_package_safety_evidence(
        self,
        safety_receipt: PackageSafetyEvidenceReceipt,
    ) -> ProviderExecutionRequest:
        """Require this request to bind one supplied package safety receipt."""

        from skills_sdk.core.digests import canonical_json_sha256
        from skills_sdk.models.safety import PackageSafetyEvidenceReceipt

        if not isinstance(safety_receipt, PackageSafetyEvidenceReceipt):
            raise ValueError("provider execution request requires package safety evidence")
        safety_receipt = PackageSafetyEvidenceReceipt.model_validate(safety_receipt.model_dump(mode="json"))
        safety_payload = safety_receipt.model_dump(mode="json")
        if self.package_safety_receipt_id != safety_receipt.receipt_id:
            raise ValueError("provider execution safety receipt id must match the supplied receipt")
        if self.package_safety_receipt_sha256 != canonical_json_sha256(safety_payload):
            raise ValueError("provider execution safety receipt digest must match the supplied receipt")
        if self.candidate != safety_receipt.candidate:
            raise ValueError("provider execution candidate must match the supplied safety receipt")
        if self.status == "prepared" and safety_receipt.status != "reviewed_no_issue":
            raise ValueError("prepared provider execution requires reviewed_no_issue safety evidence")
        return self


class ProviderExecutionResult(_ProviderExecutionContractModel):
    """Adapter-supplied execution observation; the SDK does not run a provider."""

    schema_version: Literal["provider-execution-result/v1"] = "provider-execution-result/v1"
    result_id: ExecutionId
    request_id: ExecutionId
    request_sha256: Sha256 = Field(
        description="SHA-256 of canonical JSON from the validated provider execution request model"
    )
    idempotency_key_sha256: Sha256
    candidate: PackageCandidateIdentity
    scenario_set_id: ExecutionId
    case_id: ExecutionId
    provider: ProviderIdentityV2
    status: Literal["completed", "failed", "blocked", "indeterminate"]
    started_at: AwareDatetime
    finished_at: AwareDatetime
    output_sha256: Sha256 | None = None
    usage: ProviderUsageMetadata | None = None
    evidence_refs: tuple[PortablePath, ...] = ()
    blocker: ProviderExecutionBlocker | None = None
    error: ProviderExecutionError | None = None
    replay_of_result_id: ExecutionId | None = None
    replay_of_result_sha256: Sha256 | None = Field(
        default=None,
        description="SHA-256 of canonical JSON from the validated prior provider execution result model",
    )
    sdk_execution_performed: Literal[False]
    credentials_retained: Literal[False]
    raw_payloads_retained: Literal[False]
    cost_claimed: Literal[False]

    @field_validator("started_at", "finished_at", mode="before")
    @classmethod
    def timestamps_must_be_json_strings(cls, value: object) -> object:
        if not isinstance(value, str) or _RFC3339_PATTERN.fullmatch(value) is None:
            raise ValueError("provider execution timestamps must be RFC3339 strings")
        return value

    @field_validator("candidate", mode="before")
    @classmethod
    def candidate_identity_must_already_be_normalized(cls, value: object) -> object:
        return _require_normalized_candidate(value)

    @field_validator("result_id", "request_id", "scenario_set_id", "case_id", "replay_of_result_id", mode="before")
    @classmethod
    def public_ids_must_be_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str):
            _require_normalized_text(value, "identity")
            if not _identity_is_public(value):
                raise ValueError("provider execution identity must not contain credential-shaped values")
        return value

    @field_validator(
        "request_sha256",
        "idempotency_key_sha256",
        "output_sha256",
        "replay_of_result_sha256",
        mode="before",
    )
    @classmethod
    def digests_must_already_be_normalized(cls, value: object) -> object:
        return _require_normalized_text(value, "digest bindings")

    @field_validator(
        "sdk_execution_performed",
        "credentials_retained",
        "raw_payloads_retained",
        "cost_claimed",
        mode="before",
    )
    @classmethod
    def false_only_fields_must_be_json_booleans(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("provider execution false-only fields must be JSON booleans")
        return value

    @field_validator("candidate")
    @classmethod
    def candidate_package_id_must_be_redaction_safe(
        cls, candidate: PackageCandidateIdentity
    ) -> PackageCandidateIdentity:
        if not _candidate_is_public(candidate):
            raise ValueError("provider execution candidate package id must not contain credential-shaped values")
        return candidate

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("provider execution result evidence refs must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not _identity_is_public(value):
                raise ValueError("provider execution result evidence must not contain credential-shaped values")
        return values

    @model_validator(mode="after")
    def status_matches_observation(self) -> ProviderExecutionResult:
        if (self.replay_of_result_id is None) != (self.replay_of_result_sha256 is None):
            raise ValueError("provider replay identity and digest must be supplied together")
        if self.replay_of_result_id == self.result_id:
            raise ValueError("provider execution result cannot replay itself")
        if self.finished_at < self.started_at:
            raise ValueError("provider execution result cannot finish before it starts")
        if self.status == "completed":
            if (
                self.output_sha256 is None
                or not self.evidence_refs
                or self.blocker is not None
                or self.error is not None
            ):
                raise ValueError("completed provider execution requires output evidence and no failure")
        elif self.status == "failed":
            if self.error is None or self.blocker is not None or self.output_sha256 is not None:
                raise ValueError("failed provider execution requires only a typed error")
        elif self.status == "blocked":
            if (
                self.blocker is None
                or self.error is not None
                or self.output_sha256 is not None
                or self.usage is not None
            ):
                raise ValueError("blocked provider execution requires only a blocker")
        elif self.error is None or self.blocker is not None or self.output_sha256 is not None or self.usage is not None:
            raise ValueError("indeterminate provider execution requires only a typed error")
        return self

    def validate_against_request(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        """Require this result to bind one supplied provider execution request."""

        from skills_sdk.core.digests import canonical_json_sha256

        if not isinstance(request, ProviderExecutionRequest):
            raise ValueError("provider execution result requires a provider execution request")
        request = ProviderExecutionRequest.model_validate(request.model_dump(mode="json"))
        request_payload = request.model_dump(mode="json")
        if request.status == "blocked" and self.status != "blocked":
            raise ValueError("blocked provider execution request requires a blocked result")
        if self.started_at < request.prepared_at:
            raise ValueError("provider execution result cannot start before request preparation")
        if self.request_sha256 != canonical_json_sha256(request_payload):
            raise ValueError("provider execution request digest must match the supplied request")
        if self.request_id != request.request_id:
            raise ValueError("provider execution request id must match the supplied request")
        if self.idempotency_key_sha256 != request.idempotency_key_sha256:
            raise ValueError("provider execution idempotency key must match the supplied request")
        if (self.candidate, self.scenario_set_id, self.case_id, self.provider) != (
            request.candidate,
            request.scenario_set_id,
            request.case_id,
            request.provider,
        ):
            raise ValueError("provider execution result bindings must match the supplied request")
        return self

    def validate_against_replayed_result(
        self,
        replayed_result: ProviderExecutionResult,
    ) -> ProviderExecutionResult:
        """Require replay provenance to bind one supplied prior result."""

        from skills_sdk.core.digests import canonical_json_sha256

        if not isinstance(replayed_result, ProviderExecutionResult):
            raise ValueError("provider replay provenance requires a prior provider execution result")
        replayed_result = ProviderExecutionResult.model_validate(replayed_result.model_dump(mode="json"))
        if self.replay_of_result_id != replayed_result.result_id:
            raise ValueError("provider replay result id must match the supplied prior result")
        if self.replay_of_result_sha256 != canonical_json_sha256(replayed_result.model_dump(mode="json")):
            raise ValueError("provider replay result digest must match the supplied prior result")
        return self


__all__ = [
    "ProviderExecutionBlocker",
    "ProviderExecutionError",
    "ProviderExecutionRequest",
    "ProviderExecutionResult",
    "ProviderUsageMetadata",
]
