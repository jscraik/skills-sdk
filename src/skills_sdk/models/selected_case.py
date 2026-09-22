"""Judge evidence for one selected behavioral evaluation case."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.safety import _public_text_is_redaction_safe


class SelectedCaseJudgeEvidence(_ContractModel):
    """Digest-bound semantic judgment supplied by an external judge adapter."""

    schema_version: Literal["selected-case-judge-evidence/v1"] = "selected-case-judge-evidence/v1"
    candidate: PackageCandidateIdentity
    scenario_set_id: NonEmptyText
    case_id: NonEmptyText
    provider: ProviderIdentityV2
    output_sha256: Sha256
    assertion_contract_sha256: Sha256
    judge: ProviderIdentityV2
    satisfied_assertion_ids: tuple[NonEmptyText, ...] = ()
    evidence_refs: tuple[PortablePath, ...] = Field(min_length=1)
    judge_result_sha256: Sha256
    credentials_included: Literal[False] = False
    raw_output_included: Literal[False] = False
    mutation_performed: Literal[False] = False

    @field_validator("scenario_set_id", "case_id", "satisfied_assertion_ids", mode="before")
    @classmethod
    def identity_fields_must_already_be_normalized(cls, value: object) -> object:
        values = value if isinstance(value, (list, tuple)) else (value,)
        if any(isinstance(item, str) and item != item.strip() for item in values):
            raise ValueError("selected-case judge identity fields must already be normalized")
        return value

    @field_validator("output_sha256", "assertion_contract_sha256", "judge_result_sha256", mode="before")
    @classmethod
    def digests_must_already_be_normalized(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("selected-case judge digests must already be normalized")
        return value

    @field_validator("credentials_included", "raw_output_included", "mutation_performed", mode="before")
    @classmethod
    def false_claims_must_be_json_booleans(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("selected-case judge false-only claims must be JSON booleans")
        return value

    @field_validator("satisfied_assertion_ids")
    @classmethod
    def assertion_ids_must_be_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("selected-case judge assertion ids must be unique")
        return values

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("selected-case judge evidence refs must be unique")
        for value in values:
            require_portable_relative_path(value)
            if not _public_text_is_redaction_safe(value):
                raise ValueError("selected-case judge evidence refs must not contain credential-shaped values")
        return values


__all__ = ["SelectedCaseJudgeEvidence"]
