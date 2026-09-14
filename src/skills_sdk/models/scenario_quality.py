"""Candidate-bound scenario-definition quality contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from skills_sdk.models.inventory import NonEmptyText, PortablePath, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import BlockerCode, PackageReceiptBlocker


class ScenarioQualityFinding(_ContractModel):
    code: BlockerCode
    message: NonEmptyText
    case_id: NonEmptyText | None = None
    evidence_refs: tuple[PortablePath, ...] = ()


class ScenarioQualityReceipt(_ContractModel):
    schema_version: Literal["scenario-quality/v1"] = "scenario-quality/v1"
    candidate: PackageCandidateIdentity | None = None
    scenario_set_id: NonEmptyText | None = None
    scope: Literal["all", "release"]
    status: Literal["pass", "blocked"]
    scenario_count: int = Field(ge=0)
    findings: tuple[ScenarioQualityFinding, ...] = ()
    blocker: PackageReceiptBlocker | None = None
    mutation_performed: Literal[False] = False
    network_used: Literal[False] = False
    execution_performed: Literal[False] = False

    @model_validator(mode="after")
    def status_matches_evidence(self) -> ScenarioQualityReceipt:
        if self.status == "pass" and (self.findings or self.blocker is not None or self.candidate is None):
            raise ValueError("passing scenario quality requires a candidate and no findings")
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


__all__ = ["ScenarioQualityFinding", "ScenarioQualityReceipt"]
