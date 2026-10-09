"""Capture regression fixtures and execute the complete controlled rerun."""

from __future__ import annotations

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.matched_admission import MatchedCaseExecution, preflight_matched_lane
from skills_sdk.evaluation.matched_execution import execute_matched_lane
from skills_sdk.evaluation.matched_handoff import prepare_matched_cloud_handoff
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.models.matched_execution import MatchedExecutionReceipt
from skills_sdk.models.matched_feedback import (
    MatchedCloudRegressionReceipt,
    MatchedRegressionAssignment,
    MatchedRegressionReceipt,
    _failed_case_ids,
    _require_regression_controls,
)
from skills_sdk.models.matched_handoff import MatchedCloudExecutionReceipt
from skills_sdk.models.safety import PackageSafetyBlocker
from skills_sdk.validation import validate_plugin_package


async def execute_matched_regression(
    initial: object,
    assignments: tuple[object, ...],
    plan: object,
    calibrations: tuple[object, object],
    executions: tuple[MatchedCaseExecution, ...],
) -> MatchedRegressionReceipt:
    """Observe all ten cases again; no owner declaration can substitute for proof."""
    try:
        if type(assignments) is not tuple or len(assignments) > 10:
            raise ValueError("regression ownership must be a bounded explicit tuple")
        failed = MatchedExecutionReceipt.model_validate(initial)
        selected = MatchedComparisonPlan.model_validate(plan)
        owners = tuple(MatchedRegressionAssignment.model_validate(item) for item in assignments)
        _require_regression_controls(failed, selected)
        if tuple(item.case_id for item in owners) != _failed_case_ids(failed):
            raise ValueError("every failed case requires an owner")
        problem = preflight_matched_lane(selected, failed.lane, calibrations, executions)
        if problem is not None:
            raise ValueError("regression requires an admitted complete batch")
        context = executions[0].candidate.plugin_context
        root = context.root
        before = validate_plugin_package(
            root, source_revision=selected.candidate.source_revision, policy=context.policy
        )
        if before.status != "pass" or before != selected.plugin_scope.candidate:
            raise ValueError("regression fixture source changed")
    except (AttributeError, TypeError, ValueError, ContractError):
        return MatchedRegressionReceipt(
            status="blocked",
            blocker=PackageSafetyBlocker(
                code="invalid_matched_feedback",
                message="Regression feedback requires owned failure and current controlled fixtures.",
            ),
        )
    rerun = await execute_matched_lane(selected, failed.lane, calibrations, executions)
    after = validate_plugin_package(root, source_revision=selected.candidate.source_revision, policy=context.policy)
    closed = (
        rerun.status == "completed" and not rerun.requires_regression and after.status == "pass" and before == after
    )
    return MatchedRegressionReceipt(
        initial=failed,
        assignments=owners,
        rerun=rerun,
        fixture_before=before,
        fixture_after=after,
        fixture_paths=tuple(
            sorted({f"{item.driver_skill_path}/references/evals.yaml" for item in selected.plugin_scope.cases})
        ),
        status="closed" if closed else "open",
    )


async def execute_matched_cloud_regression(
    initial: object,
    assignments: tuple[object, ...],
    plan: object,
    calibrations: tuple[object, object],
    executions: tuple[MatchedCaseExecution, ...],
) -> MatchedCloudRegressionReceipt:
    """Revalidate local lineage before executing an owned cloud regression rerun."""
    try:
        failed = MatchedCloudExecutionReceipt.model_validate(initial)
        if failed.status != "completed" or failed.handoff is None:
            raise ValueError("cloud feedback requires an executed candidate failure")
        handoff = prepare_matched_cloud_handoff(failed.handoff.local, plan)
        if handoff.status != "ready":
            raise ValueError("cloud feedback requires the same qualified local baseline")
    except (TypeError, ValueError, ContractError):
        feedback = MatchedRegressionReceipt(
            status="blocked",
            blocker=PackageSafetyBlocker(
                code="invalid_matched_feedback", message="Cloud recovery requires retained local candidate selection."
            ),
        )
        return MatchedCloudRegressionReceipt(feedback=feedback, status="blocked")
    feedback = await execute_matched_regression(
        failed.execution, assignments, handoff.cloud_plan, calibrations, executions
    )
    return MatchedCloudRegressionReceipt(
        initial=None if feedback.status == "blocked" else failed,
        handoff=None if feedback.status == "blocked" else handoff,
        feedback=feedback,
        status=feedback.status,
    )
