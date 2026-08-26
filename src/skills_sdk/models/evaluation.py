"""Portable scenario-set and scorer-profile contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from skills_sdk.models.inventory import NonEmptyText, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity


class ScenarioCase(_ContractModel):
    """One candidate-bound behavioral scenario."""

    case_id: NonEmptyText
    category: Literal["happy", "pressure", "boundary", "regression"]
    prompt: NonEmptyText
    expected_signals: tuple[NonEmptyText, ...] = Field(min_length=1)
    forbidden_commands: tuple[NonEmptyText, ...] = ()
    oracle: Literal["exact_match", "expected_signal", "structured"]


class ScenarioSet(_ContractModel):
    """Immutable scenario universe selected for one package candidate."""

    schema_version: Literal["scenario-set/v1"] = "scenario-set/v1"
    candidate: PackageCandidateIdentity
    scenario_set_id: NonEmptyText
    release: bool
    cases: tuple[ScenarioCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> ScenarioSet:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario case ids must be unique")
        if self.release and not any(case.category == "regression" for case in self.cases):
            raise ValueError("release scenario sets require a regression case")
        return self


class ScorerProfile(_ContractModel):
    """Versioned scorer identity and calibration requirements."""

    schema_version: Literal["scorer-profile/v1"] = "scorer-profile/v1"
    candidate: PackageCandidateIdentity
    scorer_id: NonEmptyText
    scorer_type: Literal["deterministic", "llm_judge", "hybrid", "external"]
    version_or_digest: NonEmptyText
    pass_threshold: float = Field(ge=0, le=1)
    deterministic_checks_first: bool
    calibration_required: bool
    calibration_probe_ids: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def calibration_matches_policy(self) -> ScorerProfile:
        if self.calibration_required and not self.calibration_probe_ids:
            raise ValueError("calibration_required scorers must declare calibration probes")
        if self.scorer_type in {"llm_judge", "external"} and not self.calibration_required:
            raise ValueError("judge and external scorers must require calibration")
        if self.scorer_type in {"llm_judge", "external"} and not self.deterministic_checks_first:
            raise ValueError("judge and external scorers must run deterministic checks first")
        if len(self.calibration_probe_ids) != len(set(self.calibration_probe_ids)):
            raise ValueError("calibration probe ids must be unique")
        return self


__all__ = ["ScenarioCase", "ScenarioSet", "ScorerProfile"]
