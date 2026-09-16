"""Candidate-bound scenario-definition quality contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import BlockerCode


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
    minimum_release_cases: Literal[5] = 5
    target_release_cases: Literal[8] = 8
    maximum_release_cases: Literal[10] = 10
    minimum_pressure_or_regression: Literal[1] = 1
    minimum_negative_or_edge: Literal[1] = 1


class ScenarioQualityReceipt(_ContractModel):
    schema_version: Literal["scenario-quality/v1"] = "scenario-quality/v1"
    candidate: PackageCandidateIdentity | None = None
    scenario_set_id: NonEmptyText | None = None
    scope: Literal["all", "release"]
    status: Literal["pass", "blocked"]
    scenario_count: int = Field(ge=0)
    pressure_or_regression_count: int = Field(default=0, ge=0)
    negative_or_edge_count: int = Field(default=0, ge=0)
    effective_policy: ScenarioQualityAppliedPolicy
    findings: tuple[ScenarioQualityFinding, ...] = ()
    mutation_performed: Literal[False] = False
    network_used: Literal[False] = False
    execution_performed: Literal[False] = False

    @model_validator(mode="after")
    def status_matches_evidence(self) -> ScenarioQualityReceipt:
        if (self.scope == "release") != (self.scenario_set_id is not None):
            raise ValueError("release scope requires exactly one scenario set identifier")
        if self.status == "pass" and (self.findings or self.candidate is None):
            raise ValueError("passing scenario quality requires a candidate and no findings")
        if self.status == "pass" and self.scenario_count == 0:
            raise ValueError("passing scenario quality requires at least one scenario")
        if self.pressure_or_regression_count > self.scenario_count:
            raise ValueError("pressure or regression count cannot exceed scenario count")
        if self.negative_or_edge_count > self.scenario_count:
            raise ValueError("negative or edge count cannot exceed scenario count")
        if (
            self.status == "pass"
            and self.scope == "release"
            and (
                self.scenario_count < self.effective_policy.minimum_release_cases
                or self.scenario_count > self.effective_policy.maximum_release_cases
                or self.pressure_or_regression_count < self.effective_policy.minimum_pressure_or_regression
                or self.negative_or_edge_count < self.effective_policy.minimum_negative_or_edge
            )
        ):
            raise ValueError("passing release quality must satisfy the effective policy")
        if self.status == "blocked" and not self.findings:
            raise ValueError("blocked scenario quality requires findings")
        return self


__all__ = ["ScenarioQualityAppliedPolicy", "ScenarioQualityFinding", "ScenarioQualityReceipt"]
