"""Versioned, candidate-bound local intake-to-check result."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, model_validator

from skills_sdk.models.intake import SkillPackageIntakeReceipt
from skills_sdk.models.inventory import _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.scenario_quality import ScenarioQualityReceiptV2
from skills_sdk.models.scorer_quality import ScorerCalibrationReceipt, ScorerQualityReceipt
from skills_sdk.models.validation import SkillPackageValidation

StageName = Literal["intake", "validate", "scenario-quality", "scorer-quality", "scorer-calibration"]
BlockedStage = StageName | Literal["candidate_changed", "context"]
StageReceipt = (
    SkillPackageIntakeReceipt
    | SkillPackageValidation
    | ScenarioQualityReceiptV2
    | ScorerQualityReceipt
    | ScorerCalibrationReceipt
)
_STAGE_TYPES = (
    ("intake", SkillPackageIntakeReceipt),
    ("validate", SkillPackageValidation),
    ("scenario-quality", ScenarioQualityReceiptV2),
    ("scorer-quality", ScorerQualityReceipt),
    ("scorer-calibration", ScorerCalibrationReceipt),
)


class LocalCheckStage(_ContractModel):
    model_config = ConfigDict(revalidate_instances="always")

    name: StageName
    receipt: StageReceipt

    @model_validator(mode="after")
    def name_matches_receipt(self) -> LocalCheckStage:
        receipt_type = dict(_STAGE_TYPES)[self.name]
        if not isinstance(self.receipt, receipt_type):
            raise ValueError("local-check stage name must match its receipt type")
        receipt_type.model_validate(self.receipt.model_dump(mode="json", warnings="error"))
        return self


class LocalCheckResult(_ContractModel):
    schema_version: Literal["local-check/v1"] = "local-check/v1"
    workflow: Literal["local-check"] = "local-check"
    status: Literal["local_checks_passed", "blocked"]
    candidate: PackageCandidateIdentity | None = None
    blocked_stage: BlockedStage | None = None
    stages: tuple[LocalCheckStage, ...] = ()
    blocker: PackageReceiptBlocker | None = None
    promotion_authorized: Literal[False] = False
    mutation_performed: Literal[False] = False
    network_used: Literal[False] = False
    execution_performed: Literal[False] = False

    @model_validator(mode="after")
    def status_matches_stage_evidence(self) -> LocalCheckResult:
        if self.blocked_stage == "context":
            if (
                self.status != "blocked"
                or self.stages
                or self.candidate is not None
                or self.blocker is None
                or self.blocker.code != "unsupported_context_read"
            ):
                raise ValueError("context blocker requires no candidate or stages")
            return self
        if not self.stages or self.blocker is not None:
            raise ValueError("stage results require an intake stage and no context blocker")
        expected = tuple(name for name, _ in _STAGE_TYPES[: len(self.stages)])
        if tuple(stage.name for stage in self.stages) != expected:
            raise ValueError("local-check stages must be a nonempty ordered prefix")
        intake = self.stages[0].receipt
        if not isinstance(intake, SkillPackageIntakeReceipt) or self.candidate != intake.candidate:
            raise ValueError("local-check candidate must match intake")
        mismatches = [
            index for index, stage in enumerate(self.stages[1:], 1) if stage.receipt.candidate != self.candidate
        ]
        if len(self.stages) > 1 and (
            intake.status != "normalized" or intake.decision is None or intake.decision.decision.value != "admit"
        ):
            raise ValueError("later checks require an admit intake")
        if any(stage.receipt.status != "pass" for stage in self.stages[1:-1]):
            raise ValueError("local check must stop at the first blocked check")
        if self.blocked_stage == "candidate_changed":
            if self.status != "blocked" or mismatches != [len(self.stages) - 1]:
                raise ValueError("candidate_changed must stop at the first mismatched stage")
            return self
        if mismatches:
            raise ValueError("local-check stage candidates must match intake")
        if self.status == "local_checks_passed":
            if self.blocked_stage is not None or len(self.stages) != len(_STAGE_TYPES) or self.candidate is None:
                raise ValueError("passing local check requires every stage and a candidate")
            if intake.status != "normalized" or intake.decision is None or intake.decision.decision.value != "admit":
                raise ValueError("passing local check requires an admit intake")
            if any(stage.receipt.status != "pass" for stage in self.stages[1:]):
                raise ValueError("passing local check requires all checks to pass")
        elif self.blocked_stage is None or self.blocked_stage != self.stages[-1].name:
            raise ValueError("blocked local check must identify its last stage")
        elif self.blocked_stage == "intake":
            if (
                intake.status == "normalized"
                and intake.decision is not None
                and intake.decision.decision.value == "admit"
            ):
                raise ValueError("admit intake cannot be the blocked stage")
        elif self.stages[-1].receipt.status != "blocked":
            raise ValueError("blocked local check requires a blocked final receipt")
        return self


__all__ = ["LocalCheckResult", "LocalCheckStage"]
