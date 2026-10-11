"""Candidate-bound local selection before an independently matched cloud lane."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import field_validator, model_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.models.matched_execution import MatchedExecutionReceipt
from skills_sdk.models.matched_ingress import _MatchedContractModel
from skills_sdk.models.safety import PackageSafetyBlocker


def _require_local_handoff(local: MatchedExecutionReceipt, cloud: MatchedComparisonPlan) -> None:
    if local.status != "completed" or local.lane != "local" or local.plan is None or local.requires_regression:
        raise ValueError("cloud handoff requires complete local evidence without unresolved regressions")
    if local.summary is None or local.summary.decision != "candidate":
        raise ValueError("cloud handoff requires qualifying within-model local improvement")
    if (
        cloud.plugin_scope.baseline != local.plan.plugin_scope.candidate
        or tuple(item.baseline_input_sha256 for item in cloud.case_bindings)
        != tuple(item.candidate_input_sha256 for item in local.plan.case_bindings)
        or cloud.plugin_scope.baseline == cloud.plugin_scope.candidate
        or cloud.baseline_scenarios != local.plan.candidate_scenarios
        or cloud.plugin_scope.baseline_coverage != local.plan.plugin_scope.candidate_coverage
        or cloud.rubric != local.plan.rubric
        or cloud.selection_policy != local.plan.selection_policy
        or tuple(item.semantic_signal_ids for item in cloud.case_bindings)
        != tuple(item.semantic_signal_ids for item in local.plan.case_bindings)
        or tuple(item.assertion_contract_sha256 for item in cloud.case_bindings)
        != tuple(item.assertion_contract_sha256 for item in local.plan.case_bindings)
        or tuple(item.check_contract_sha256 for item in cloud.case_bindings)
        != tuple(item.check_contract_sha256 for item in local.plan.case_bindings)
        or tuple(item.baseline_scenario_set_id for item in cloud.case_bindings)
        != tuple(item.candidate_scenario_set_id for item in local.plan.case_bindings)
        or any(
            before.candidate_scorer != after.baseline_scorer
            or before.model_dump(exclude={"baseline_scorer", "candidate_scorer"})
            != after.model_dump(exclude={"baseline_scorer", "candidate_scorer"})
            for before, after in zip(local.plan.plugin_scope.cases, cloud.plugin_scope.cases, strict=True)
        )
    ):
        raise ValueError("cloud experiment must preserve the selected local candidate, cases and scoring policy")


class MatchedCloudHandoff(_MatchedContractModel):
    """Recomputed local-to-cloud selection, never permission for spending or promotion."""

    schema_version: Literal["matched-cloud-handoff/v1"] = "matched-cloud-handoff/v1"
    local: MatchedExecutionReceipt | None = None
    cloud_plan: MatchedComparisonPlan | None = None
    local_receipt_sha256: str | None = None
    status: Literal["ready", "blocked"]
    blocker: PackageSafetyBlocker | None = None
    promotion_authorized: Literal[False] = False

    _ingress_work_limit: ClassVar[int] = 4500000

    @field_validator("promotion_authorized", mode="before")
    @classmethod
    def false_only(cls, value: object) -> object:
        if value is not False:
            raise ValueError("cloud handoff cannot authorise promotion")
        return value

    @model_validator(mode="after")
    def selection_matches_evidence(self) -> MatchedCloudHandoff:
        if self.local_receipt_sha256 != (
            None if self.local is None else canonical_json_sha256(self.local.model_dump(mode="json"))
        ):
            raise ValueError("cloud handoff must bind the complete retained local receipt")
        eligible = False
        if self.local is not None and self.cloud_plan is not None:
            try:
                _require_local_handoff(self.local, self.cloud_plan)
                eligible = True
            except ValueError:
                pass
        if self.status == "ready":
            if not eligible or self.blocker is not None:
                raise ValueError("ready cloud handoff requires qualifying local evidence and matching cloud baseline")
        elif eligible or self.blocker is None or self.blocker.code != "invalid_matched_handoff":
            raise ValueError("blocked cloud handoff must describe an ineligible selection")
        return self


class MatchedCloudExecutionReceipt(_MatchedContractModel):
    """Retain the local selection alongside its bound cloud callback evidence."""

    schema_version: Literal["matched-cloud-execution/v1"] = "matched-cloud-execution/v1"
    handoff: MatchedCloudHandoff | None = None
    handoff_sha256: str | None = None
    execution: MatchedExecutionReceipt
    status: Literal["completed", "blocked"]
    promotion_authorized: Literal[False] = False

    _ingress_work_limit: ClassVar[int] = 8000000

    @field_validator("promotion_authorized", mode="before")
    @classmethod
    def false_only(cls, value: object) -> object:
        return MatchedCloudHandoff.false_only(value)

    @model_validator(mode="after")
    def cloud_evidence_retains_local_selection(self) -> MatchedCloudExecutionReceipt:
        if (
            self.handoff_sha256
            != (None if self.handoff is None else canonical_json_sha256(self.handoff.model_dump(mode="json")))
            or self.status != self.execution.status
        ):
            raise ValueError("cloud execution must bind its handoff digest and actual outcome")
        if self.handoff is None or self.handoff.status != "ready":
            if self.status != "blocked" or self.execution.plan is not None or self.execution.provider_invocation_count:
                raise ValueError("unqualified cloud handoff cannot retain execution")
        elif self.execution.plan != self.handoff.cloud_plan or self.execution.lane != "cloud":
            raise ValueError("cloud execution must retain its selected candidate and frozen cloud plan")
        return self
