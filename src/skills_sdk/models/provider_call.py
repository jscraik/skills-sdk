"""Public evidence contracts for bounded offline provider calls."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from skills_sdk.models.inventory import Sha256, _ContractModel
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_execution import ExecutionId, ProviderExecutionResult, ProviderUsageMetadata


class _ProviderCallModel(_ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True, revalidate_instances="always")


class TextProviderAdapterDescriptor(_ProviderCallModel):
    """Immutable identity and selected offline behavior for one injected adapter."""

    schema_version: Literal["provider-call-adapter/v1"] = "provider-call-adapter/v1"
    provider: ProviderIdentityV2
    mode: Literal["complete", "stream"]
    capabilities: tuple[Literal["response_generation"], ...] = ("response_generation",)
    discovery: Literal["injected"] = "injected"
    transport: Literal["offline"] = "offline"
    credentials_included: Literal[False] = False

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != ("response_generation",):
            raise ValueError("offline text adapter must declare only response_generation")
        return values


DecimalString = Annotated[Decimal, WithJsonSchema({"type": "string", "pattern": r"^(?:0|[1-9]\d*)(?:\.\d+)?$"})]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class ProviderCostObservation(_ProviderCallModel):
    """Adapter-reported decimal cost observation, not an SDK measurement."""

    amount: DecimalString
    currency: CurrencyCode
    observed_at: AwareDatetime
    claimed_by: Literal["adapter"] = "adapter"

    @field_validator("amount", mode="before")
    @classmethod
    def amount_is_a_decimal_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("provider cost amount must be a decimal string")
        if re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d+)?", value) is None:
            raise ValueError("provider cost amount must be a decimal string")
        try:
            amount = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("provider cost amount must be a decimal string") from error
        if not amount.is_finite() or amount < 0:
            raise ValueError("provider cost amount must be finite and non-negative")
        return amount

    @field_validator("observed_at", mode="before")
    @classmethod
    def observed_at_is_a_wire_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("provider cost observed_at must be an RFC3339 string")
        return value


class ProviderCallPublicResult(_ProviderCallModel):
    """Compact public evidence for one bounded provider-call orchestration."""

    schema_version: Literal["provider-call-result/v1"] = "provider-call-result/v1"
    request_id: ExecutionId
    mode: Literal["complete", "stream"]
    status: Literal["completed", "failed", "blocked", "indeterminate"]
    event_count: int = Field(ge=0, le=4096)
    output_bytes: int = Field(ge=0, le=1_048_576)
    output_sha256: Sha256 | None = None
    event_sha256: Sha256
    max_inflight_pulls: Literal[1] = 1
    max_buffered_events: int = Field(ge=0, le=8)
    retry_attempts: Literal[0] = 0
    cleanup_attempted: bool
    cleanup_succeeded: bool | None
    cleanup_error_code: Literal["cleanup_failed"] | None = None
    usage: ProviderUsageMetadata | None = None
    cost: ProviderCostObservation | None = None
    execution: ProviderExecutionResult

    @model_validator(mode="before")
    @classmethod
    def nested_models_are_revalidated(cls, value: object) -> object:
        if isinstance(value, cls):
            value = value.model_dump(mode="json")
        if isinstance(value, Mapping):
            normalized = dict(value)
            for field in ("usage", "cost", "execution"):
                nested = normalized.get(field)
                if isinstance(nested, BaseModel):
                    normalized[field] = nested.model_dump(mode="json")
            return normalized
        return value

    @field_validator(
        "event_count",
        "output_bytes",
        "max_inflight_pulls",
        "max_buffered_events",
        "retry_attempts",
        mode="before",
    )
    @classmethod
    def counts_are_json_integers(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("provider call counts must be JSON integers")
        return value

    @field_validator("cleanup_attempted", "cleanup_succeeded", mode="before")
    @classmethod
    def cleanup_flags_are_json_booleans(cls, value: object) -> object:
        if value is not None and type(value) is not bool:
            raise ValueError("provider call cleanup flags must be JSON booleans")
        return value

    @model_validator(mode="after")
    def result_is_consistent(self) -> ProviderCallPublicResult:
        if self.request_id != self.execution.request_id or self.status != self.execution.status:
            raise ValueError("provider call result must match its execution evidence")
        if self.cleanup_attempted != (self.cleanup_succeeded is not None):
            raise ValueError("provider call cleanup result requires an attempted cleanup")
        if (self.cleanup_succeeded is False) != (self.cleanup_error_code == "cleanup_failed"):
            raise ValueError("provider call cleanup failure requires redacted diagnostic evidence")
        if self.status == "completed":
            if self.output_sha256 is None or self.output_sha256 != self.execution.output_sha256:
                raise ValueError("completed provider call must bind its output digest")
        elif self.output_sha256 is not None or self.output_bytes != 0:
            raise ValueError("non-completed provider call cannot expose output evidence")
        if self.usage != self.execution.usage:
            raise ValueError("provider call usage must match execution evidence")
        return self


__all__ = [
    "ProviderCallPublicResult",
    "ProviderCostObservation",
    "TextProviderAdapterDescriptor",
]
