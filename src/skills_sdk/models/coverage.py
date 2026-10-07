"""Candidate-bound claim-to-case-or-gap audit contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from skills_sdk.models.inventory import NonEmptyText, PackageId, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.scenario_quality import ScenarioQualityFinding, ScenarioQualityReceiptV2

CoverageId = PackageId
ExactCaseId = Annotated[str, StringConstraints(strip_whitespace=False, min_length=1, pattern=r"\S")]


class _CoverageModel(_ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class CoverageClaim(_CoverageModel):
    id: CoverageId
    statement: NonEmptyText


class CoverageGap(_CoverageModel):
    id: CoverageId
    reason: NonEmptyText
    owner: NonEmptyText


class ClaimCoverage(_CoverageModel):
    claim_id: CoverageId
    case_ids: tuple[ExactCaseId, ...] = ()
    gap_ids: tuple[CoverageId, ...] = ()


class ScenarioCoveragePlan(_CoverageModel):
    schema_version: Literal["scenario-coverage-plan/v1"] = "scenario-coverage-plan/v1"
    candidate: PackageCandidateIdentity
    scenario_set_id: NonEmptyText
    claims: tuple[CoverageClaim, ...] = Field(min_length=1)
    mappings: tuple[ClaimCoverage, ...] = ()
    gaps: tuple[CoverageGap, ...] = ()

    def audit(self, active_case_ids: tuple[str, ...]) -> tuple[ScenarioQualityFinding, ...]:
        """Check declared coverage, not whether a case actually proves a claim."""
        findings: list[ScenarioQualityFinding] = []
        claim_ids = [claim.id for claim in self.claims]
        gap_ids = [gap.id for gap in self.gaps]
        mapped_ids = [item.claim_id for item in self.mappings]
        if any(len(ids) != len(set(ids)) for ids in (claim_ids, gap_ids, mapped_ids)):
            findings.append(ScenarioQualityFinding(code="duplicate_coverage_id", message="coverage ids must be unique"))
        if set(mapped_ids) != set(claim_ids):
            findings.append(
                ScenarioQualityFinding(code="unmapped_claim", message="map every declared claim exactly once")
            )
        used_gaps: set[str] = set()
        for item in self.mappings:
            used_gaps.update(item.gap_ids)
            invalid = (
                (not item.case_ids and not item.gap_ids)
                or len(item.case_ids) != len(set(item.case_ids))
                or len(item.gap_ids) != len(set(item.gap_ids))
                or not set(item.case_ids).issubset(active_case_ids)
                or not set(item.gap_ids).issubset(gap_ids)
            )
            if invalid:
                findings.append(
                    ScenarioQualityFinding(
                        code="invalid_claim_mapping", message="map claims only to active cases or declared gaps"
                    )
                )
        if used_gaps != set(gap_ids):
            findings.append(ScenarioQualityFinding(code="unused_coverage_gap", message="every gap must map to a claim"))
        return tuple(findings)


class ScenarioCoverageResult(_CoverageModel):
    schema_version: Literal["scenario-coverage/v1"] = "scenario-coverage/v1"
    candidate: PackageCandidateIdentity | None
    scenario_set_id: NonEmptyText | None
    status: Literal["pass", "blocked"]
    quality: ScenarioQualityReceiptV2
    plan: ScenarioCoveragePlan | None = None
    active_case_ids: tuple[ExactCaseId, ...] = ()
    open_gap_ids: tuple[CoverageId, ...] = ()
    coverage_complete: bool = False
    findings: tuple[ScenarioQualityFinding, ...] = ()
    promotion_authorized: Literal[False] = False
    mutation_performed: Literal[False] = False
    network_used: Literal[False] = False
    execution_performed: Literal[False] = False

    @model_validator(mode="after")
    def result_matches_evidence(self) -> ScenarioCoverageResult:
        ScenarioQualityReceiptV2.model_validate(self.quality.model_dump(mode="json", warnings="error"))
        if self.candidate != self.quality.candidate or self.scenario_set_id != self.quality.scenario_set_id:
            raise ValueError("coverage must bind its quality receipt")
        if len(self.active_case_ids) != len(set(self.active_case_ids)):
            raise ValueError("active coverage case ids must be unique")
        if self.plan is not None:
            ScenarioCoveragePlan.model_validate(self.plan.model_dump(mode="json", warnings="error"))
        expected_gaps = tuple(sorted(gap.id for gap in self.plan.gaps)) if self.plan else ()
        if self.open_gap_ids != expected_gaps:
            raise ValueError("coverage must preserve all declared gaps")
        if self.status == "pass":
            if self.findings or self.quality.status != "pass" or self.plan is None or len(self.active_case_ids) != 10:
                raise ValueError("passing coverage requires quality, a plan, ten active cases and no findings")
            if self.plan.candidate != self.candidate or self.plan.scenario_set_id != self.scenario_set_id:
                raise ValueError("passing coverage plan must bind the same candidate and set")
            if self.plan.audit(self.active_case_ids):
                raise ValueError("passing coverage requires a complete declared map")
        elif not self.findings:
            raise ValueError("blocked coverage requires findings")
        if self.coverage_complete != (self.status == "pass" and not self.open_gap_ids):
            raise ValueError("coverage completeness requires a passing audit without open gaps")
        return self


__all__ = ["ClaimCoverage", "CoverageClaim", "CoverageGap", "ScenarioCoveragePlan", "ScenarioCoverageResult"]
