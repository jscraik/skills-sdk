"""Bound complete plugin captures to the existing ten-case claim coverage map."""

from __future__ import annotations

import re
from typing import ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.coverage import ScenarioCoveragePlan
from skills_sdk.models.evaluation import ScorerProfile
from skills_sdk.models.inventory import PortablePath
from skills_sdk.models.matched_ingress import _MatchedContractModel
from skills_sdk.models.plugin import PluginPackageValidation
from skills_sdk.models.safety import _public_text_is_redaction_safe


def _skill_path(value: str) -> str:
    """Accept only exact direct child paths in the portable skill namespace."""
    require_portable_relative_path(value)
    parts = value.split("/")
    if len(parts) != 2 or parts[0] != "skills" or value != value.strip():
        raise ValueError("matched plugin skill path requires an exact direct child")
    return value


class MatchedPluginCaseScope(_MatchedContractModel):
    """One declared managed case, its driver scorer and existing coverage claims."""

    case_id: str = Field(min_length=1, max_length=128)
    scope: Literal["per_skill", "cross_skill"]
    driver_skill_path: PortablePath
    selected_skill_paths: tuple[PortablePath, ...] = Field(min_length=1, max_length=9)
    baseline_scorer: ScorerProfile
    candidate_scorer: ScorerProfile
    claim_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    reference_paths: tuple[PortablePath, ...] = Field(default=(), max_length=64)

    @field_validator("reference_paths", mode="before")
    @classmethod
    def exact_reference_paths(cls, value: object) -> object:
        """Keep case-level reference selection explicit and identical across variants."""
        if type(value) not in (list, tuple) or any(type(path) is not str for path in value):
            raise ValueError("matched references require exact string paths")
        if tuple(value) != tuple(sorted(set(value))):
            raise ValueError("matched references require unique sorted paths")
        for path in value:
            require_portable_relative_path(path)
            if path != path.strip() or not _public_text_is_redaction_safe(path):
                raise ValueError("matched references must be exact public paths")
        return value

    @field_validator("claim_ids", mode="before")
    @classmethod
    def exact_claim_ids(cls, value: object) -> object:
        """Preserve existing coverage identifier syntax without trimming input."""
        if type(value) not in (list, tuple) or any(
            type(item) is not str or re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", item) is None for item in value
        ):
            raise ValueError("matched claims require exact existing coverage identifiers")
        return value

    @field_validator("case_id", mode="before")
    @classmethod
    def case_token(cls, value: object) -> object:
        """Avoid silently trimming managed case identifiers."""
        if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value) is None:
            raise ValueError("matched plugin case requires an exact public identifier")
        return value

    @field_validator("driver_skill_path", mode="before")
    @classmethod
    def direct_driver(cls, value: object) -> str:
        """Validate the driver as a portable direct skill directory."""
        if type(value) is not str:
            raise ValueError("matched driver path requires an exact string")
        return _skill_path(value)

    @field_validator("selected_skill_paths", mode="before")
    @classmethod
    def exact_selected_paths(cls, value: object) -> object:
        """Check raw selections before shared string normalization."""
        if type(value) not in (list, tuple) or any(type(item) is not str or item != item.strip() for item in value):
            raise ValueError("matched selections require exact unpadded paths")
        return value

    @field_validator("selected_skill_paths", "claim_ids")
    @classmethod
    def exact_sorted_members(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Canonicalize neither order nor identifiers supplied by the caller."""
        if value != tuple(sorted(set(value))) or any(item != item.strip() for item in value):
            raise ValueError("matched plugin selections require sorted unique exact identifiers")
        return value

    @model_validator(mode="after")
    def scope_matches_selection(self) -> Self:
        """Cross-skill cases select multiple children; per-skill cases select their driver."""
        for path in self.selected_skill_paths:
            _skill_path(path)
        if self.driver_skill_path not in self.selected_skill_paths:
            raise ValueError("matched plugin driver must be selected")
        if self.scope == "per_skill" and self.selected_skill_paths != (self.driver_skill_path,):
            raise ValueError("per-skill scope selects exactly its driver")
        if self.scope == "cross_skill" and len(self.selected_skill_paths) < 2:
            raise ValueError("cross-skill scope requires at least two selected children")
        if any(
            path.split("/")[0] == "skills" and "/".join(path.split("/")[:2]) not in self.selected_skill_paths
            for path in self.reference_paths
        ):
            raise ValueError("matched references within skills must belong to a selected child")
        if self.baseline_scorer.model_dump(exclude={"candidate"}) != self.candidate_scorer.model_dump(
            exclude={"candidate"}
        ):
            raise ValueError("matched child scorer contracts must agree across variants")
        if any(
            not scorer.calibration_required or not scorer.deterministic_checks_first
            for scorer in (self.baseline_scorer, self.candidate_scorer)
        ):
            raise ValueError("matched child scorers require calibrated deterministic-first policy")
        return self


class MatchedPluginScope(_MatchedContractModel):
    """Ten-case structural scope; claim accuracy and fresh source remain separate proof."""

    baseline: PluginPackageValidation
    candidate: PluginPackageValidation
    cases: tuple[MatchedPluginCaseScope, ...] = Field(min_length=10, max_length=10)
    baseline_coverage: ScenarioCoveragePlan
    candidate_coverage: ScenarioCoveragePlan

    _ingress_work_limit: ClassVar[int] = 524288

    @model_validator(mode="after")
    def complete_scope(self) -> Self:
        """Join passing captures, child drivers and a frozen complete claim map."""
        for capture in (self.baseline, self.candidate):
            if capture.status != "pass" or capture.candidate is None:
                raise ValueError("matched plugin scope requires passing complete captures")
        left = {child.path: child.validation.candidate for child in self.baseline.skills}
        right = {child.path: child.validation.candidate for child in self.candidate.skills}
        if set(left) != set(right):
            raise ValueError("matched plugin child inventory must agree across variants")
        if not 1 <= len(left) <= 9:
            raise PydanticCustomError(
                "matched_plugin_capacity", "ten-case slice supports one through nine child skills"
            )
        case_ids = tuple(case.case_id for case in self.cases)
        if len(set(case_ids)) != 10:
            raise ValueError("matched plugin scope requires ten unique ordered case identifiers")
        drivers = {case.driver_skill_path for case in self.cases if case.scope == "per_skill"}
        if drivers != set(left):
            raise ValueError("every captured child requires a per-skill driver case")
        if len(left) > 1 and not any(case.scope == "cross_skill" for case in self.cases):
            raise ValueError("multi-skill plugin scope requires a cross-skill case")
        for case in self.cases:
            if not set(case.selected_skill_paths) <= set(left):
                raise ValueError("matched case selects an unknown captured child")
            if case.baseline_scorer.candidate != left[case.driver_skill_path] or (
                case.candidate_scorer.candidate != right[case.driver_skill_path]
            ):
                raise ValueError("matched case scorer must bind its exact driver child")
            if any(
                not set(case.reference_paths) <= {item.path for item in capture.files}
                for capture in (self.baseline, self.candidate)
            ):
                raise ValueError("matched references require both complete variant captures")
        self._require_coverage(case_ids)
        return self

    def _require_coverage(self, case_ids: tuple[str, ...]) -> None:
        """Reuse coverage audits and require the same objective across variants."""
        for capture, coverage in ((self.baseline, self.baseline_coverage), (self.candidate, self.candidate_coverage)):
            if coverage.candidate != capture.candidate or coverage.gaps or coverage.audit(case_ids):
                raise ValueError("matched plugin coverage requires bound complete mapping without open gaps")
        if self.baseline_coverage.model_dump(exclude={"candidate"}) != self.candidate_coverage.model_dump(
            exclude={"candidate"}
        ):
            raise ValueError("matched plugin variants must freeze the same coverage objective")
        for case in self.cases:
            expected = tuple(
                sorted(
                    mapping.claim_id for mapping in self.baseline_coverage.mappings if case.case_id in mapping.case_ids
                )
            )
            if case.claim_ids != expected:
                raise ValueError("matched case claims must equal the existing coverage mappings")


__all__ = ["MatchedPluginCaseScope", "MatchedPluginScope"]
