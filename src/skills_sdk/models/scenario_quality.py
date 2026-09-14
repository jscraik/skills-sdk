"""Candidate-bound scenario-definition quality contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import BlockerCode, PackageReceiptBlocker


class ScenarioQualityFinding(_ContractModel):
    code: BlockerCode
    message: NonEmptyText
    case_id: NonEmptyText | None = None
    evidence_refs: tuple[PortablePath, ...] = ()

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            require_portable_relative_path(value)
        return values


class ScenarioQualityAppliedPolicy(_ContractModel):
    minimum_release_cases: int = Field(ge=0)
    minimum_pressure_or_regression: int = Field(ge=0)
    minimum_negative_or_edge: int = Field(ge=0)


class ScenarioQualityReceipt(_ContractModel):
    schema_version: Literal["scenario-quality/v1"] = "scenario-quality/v1"
    candidate: PackageCandidateIdentity | None = None
    scenario_set_id: NonEmptyText | None = None
    scope: Literal["all", "release"]
    status: Literal["pass", "blocked"]
    scenario_count: int = Field(ge=0)
    effective_policy: ScenarioQualityAppliedPolicy
    findings: tuple[ScenarioQualityFinding, ...] = ()
    blocker: PackageReceiptBlocker | None = None
    mutation_performed: Literal[False] = False
    network_used: Literal[False] = False
    execution_performed: Literal[False] = False

    @model_validator(mode="after")
    def status_matches_evidence(self) -> ScenarioQualityReceipt:
        if (self.scope == "release") != (self.scenario_set_id is not None):
            raise ValueError("release scope requires exactly one scenario set identifier")
        if self.status == "pass" and (self.findings or self.blocker is not None or self.candidate is None):
            raise ValueError("passing scenario quality requires a candidate and no findings")
        if self.status == "pass" and self.scenario_count == 0:
            raise ValueError("passing scenario quality requires at least one scenario")
        if self.status == "blocked" and (not self.findings or self.blocker is None):
            raise ValueError("blocked scenario quality requires findings and a primary blocker")
        if self.findings and self.blocker is not None:
            first = self.findings[0]
            if (self.blocker.code, self.blocker.message, self.blocker.evidence_refs) != (
                first.code,
                first.message,
                first.evidence_refs,
            ):
                raise ValueError("scenario quality blocker must match the first finding")
        return self


__all__ = ["ScenarioQualityAppliedPolicy", "ScenarioQualityFinding", "ScenarioQualityReceipt"]
