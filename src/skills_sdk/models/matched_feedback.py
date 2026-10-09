"""Owned regression feedback closed only by candidate-bound rerun evidence."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.models.inventory import NonEmptyText, PortablePath
from skills_sdk.models.matched_comparison import MatchedComparisonPlan, _MatchedPublicModel
from skills_sdk.models.matched_execution import MatchedExecutionReceipt
from skills_sdk.models.matched_handoff import MatchedCloudExecutionReceipt, MatchedCloudHandoff
from skills_sdk.models.matched_ingress import _MatchedContractModel
from skills_sdk.models.plugin import PluginPackageValidation
from skills_sdk.models.safety import PackageSafetyBlocker


class MatchedRegressionAssignment(_MatchedPublicModel):
    """Public owner of one observed failed case, without private contact data."""

    case_id: NonEmptyText
    owner: NonEmptyText


def _failed_case_ids(execution: MatchedExecutionReceipt) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            pair.case_id
            for pair in execution.pairs
            if pair.candidate_evaluation.status != "pass" or execution._pair_regression_required(pair)
        )
    )


def _require_regression_controls(initial: MatchedExecutionReceipt, plan: MatchedComparisonPlan) -> None:
    if initial.status != "completed" or initial.plan is None or not initial.requires_regression:
        raise ValueError("regression feedback requires a completed failing matched execution")
    old = initial.plan
    if (
        old.plugin_scope.baseline != plan.plugin_scope.baseline
        or old.candidate.package_id != plan.candidate.package_id
        or old.baseline_scenarios != plan.baseline_scenarios
        or tuple(item.cases for item in old.candidate_scenarios)
        != tuple(item.cases for item in plan.candidate_scenarios)
        or old.rubric != plan.rubric
        or old.selection_policy != plan.selection_policy
        or tuple(item.semantic_signal_ids for item in old.case_bindings)
        != tuple(item.semantic_signal_ids for item in plan.case_bindings)
        or old.plugin_scope.baseline_coverage != plan.plugin_scope.baseline_coverage
        or old.plugin_scope.candidate_coverage.model_dump(exclude={"candidate"})
        != plan.plugin_scope.candidate_coverage.model_dump(exclude={"candidate"})
        or any(
            left.model_dump(exclude={"candidate_scorer": {"candidate"}})
            != right.model_dump(exclude={"candidate_scorer": {"candidate"}})
            for left, right in zip(old.plugin_scope.cases, plan.plugin_scope.cases, strict=True)
        )
        or [(item.case_id, item.assertion_contract_sha256) for item in old.case_bindings]
        != [(item.case_id, item.assertion_contract_sha256) for item in plan.case_bindings]
        or tuple(item.check_contract_sha256 for item in old.case_bindings)
        != tuple(item.check_contract_sha256 for item in plan.case_bindings)
        or tuple(item.baseline_input_sha256 for item in old.case_bindings)
        != tuple(item.baseline_input_sha256 for item in plan.case_bindings)
        or [item.model_dump(exclude={"candidate_calibration_sha256"}) for item in old.lanes]
        != [item.model_dump(exclude={"candidate_calibration_sha256"}) for item in plan.lanes]
    ):
        raise ValueError("regression rerun must preserve baseline calibration, cases, assertions and model controls")


class MatchedRegressionReceipt(_MatchedContractModel):
    """Actual rerun and fixture captures, not a self-attested fixed flag."""

    schema_version: Literal["matched-regression/v1"] = "matched-regression/v1"
    initial: MatchedExecutionReceipt | None = None
    assignments: tuple[MatchedRegressionAssignment, ...] = Field(default=(), max_length=10)
    rerun: MatchedExecutionReceipt | None = None
    fixture_before: PluginPackageValidation | None = None
    fixture_after: PluginPackageValidation | None = None
    fixture_paths: tuple[PortablePath, ...] = Field(default=(), max_length=9)
    status: Literal["closed", "open", "blocked"]
    blocker: PackageSafetyBlocker | None = None
    promotion_authorized: Literal[False] = False

    _ingress_work_limit: ClassVar[int] = 6500000

    @field_validator("promotion_authorized", mode="before")
    @classmethod
    def false_only(cls, value: object) -> object:
        if value is not False:
            raise ValueError("regression feedback cannot authorise promotion")
        return value

    @model_validator(mode="after")
    def closure_requires_bound_rerun(self) -> MatchedRegressionReceipt:
        if self.status == "blocked":
            if (
                self.initial is not None
                or self.rerun is not None
                or self.assignments
                or self.fixture_before is not None
                or self.fixture_after is not None
                or self.fixture_paths
                or self.blocker is None
                or self.blocker.code != "invalid_matched_feedback"
            ):
                raise ValueError("input-blocked feedback cannot claim observed rerun or fixture capture")
            return self
        if self.initial is None or self.rerun is None or self.rerun.plan is None:
            raise ValueError("feedback requires initial failure and a bound rerun")
        _require_regression_controls(self.initial, self.rerun.plan)
        if self.rerun.lane != self.initial.lane or tuple(item.case_id for item in self.assignments) != _failed_case_ids(
            self.initial
        ):
            raise ValueError("feedback must assign every failed case once and preserve its model lane")
        if self.fixture_before is None or self.fixture_after is None:
            raise ValueError("feedback requires actual before and after fixture captures")
        expected = tuple(
            sorted({f"{item.driver_skill_path}/references/evals.yaml" for item in self.rerun.plan.plugin_scope.cases})
        )
        if (
            self.fixture_before.status != "pass"
            or self.fixture_before != self.rerun.plan.plugin_scope.candidate
            or self.fixture_paths != expected
            or not set(expected) <= {item.path for item in self.fixture_before.files}
        ):
            raise ValueError("regression fixture must bind the rerun candidate")
        closed = (
            self.rerun.status == "completed"
            and not self.rerun.requires_regression
            and self.fixture_after.status == "pass"
            and self.fixture_after == self.fixture_before
        )
        if (self.status == "closed") != closed or self.blocker is not None:
            raise ValueError("feedback closure must equal complete passing rerun and unchanged fixture evidence")
        return self


class MatchedCloudRegressionReceipt(_MatchedContractModel):
    """Cloud recovery retains its original execution and local selection lineage."""

    schema_version: Literal["matched-cloud-regression/v1"] = "matched-cloud-regression/v1"
    initial: MatchedCloudExecutionReceipt | None = None
    handoff: MatchedCloudHandoff | None = None
    feedback: MatchedRegressionReceipt
    status: Literal["closed", "open", "blocked"]
    promotion_authorized: Literal[False] = False

    _ingress_work_limit: ClassVar[int] = 16000000

    @field_validator("promotion_authorized", mode="before")
    @classmethod
    def false_only(cls, value: object) -> object:
        return MatchedRegressionReceipt.false_only(value)

    @model_validator(mode="after")
    def recovery_retains_local_lineage(self) -> MatchedCloudRegressionReceipt:
        if self.status != self.feedback.status:
            raise ValueError("cloud recovery status must match its observed feedback")
        if self.status == "blocked":
            if self.initial is not None or self.handoff is not None:
                raise ValueError("input-blocked cloud recovery cannot claim selected lineage")
        elif (
            self.initial is None
            or self.initial.status != "completed"
            or self.initial.handoff is None
            or self.handoff is None
            or self.handoff.status != "ready"
            or self.handoff.local != self.initial.handoff.local
            or self.feedback.initial != self.initial.execution
            or self.feedback.rerun is None
            or self.feedback.rerun.plan != self.handoff.cloud_plan
        ):
            raise ValueError("cloud recovery must preserve its initial failure and local candidate selection")
        return self
