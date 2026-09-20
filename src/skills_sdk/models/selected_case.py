"""Judge evidence for one selected behavioral evaluation case."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_execution import _identity_is_public


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
            if not _identity_is_public(value):
                raise ValueError("selected-case judge evidence refs must not contain credential-shaped values")
        return values


__all__ = ["SelectedCaseJudgeEvidence"]
