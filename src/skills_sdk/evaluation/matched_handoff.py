"""Local winner selection and bounded cloud dispatch without provider discovery."""

from __future__ import annotations

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.matched_admission import MatchedCaseExecution
from skills_sdk.evaluation.matched_execution import execute_matched_lane
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.models.matched_execution import MatchedExecutionReceipt
from skills_sdk.models.matched_handoff import MatchedCloudExecutionReceipt, MatchedCloudHandoff, _require_local_handoff
from skills_sdk.models.safety import PackageSafetyBlocker


def prepare_matched_cloud_handoff(local: object, cloud_plan: object) -> MatchedCloudHandoff:
    """Revalidate complete local proof and select its candidate as cloud baseline."""
    observed = None
    plan = None
    try:
        observed = MatchedExecutionReceipt.model_validate(local)
        plan = MatchedComparisonPlan.model_validate(cloud_plan)
        _require_local_handoff(observed, plan)
    except (TypeError, ValueError, ContractError):
        return MatchedCloudHandoff(
            local=observed,
            cloud_plan=plan,
            local_receipt_sha256=None if observed is None else canonical_json_sha256(observed.model_dump(mode="json")),
            status="blocked",
            blocker=PackageSafetyBlocker(
                code="invalid_matched_handoff",
                message="Cloud comparison requires a qualified local candidate and unchanged controlled cases.",
            ),
        )
    return MatchedCloudHandoff(
        local=observed,
        cloud_plan=plan,
        local_receipt_sha256=canonical_json_sha256(observed.model_dump(mode="json")),
        status="ready",
    )


async def execute_matched_cloud(
    handoff: object, calibrations: tuple[object, object], executions: tuple[MatchedCaseExecution, ...]
) -> MatchedCloudExecutionReceipt:
    """Require local selection before accessing any cloud adapter capability.

    Callers supply explicitly authorised adapters. This service does not discover
    credentials, authorise provider spending or claim authenticated execution.
    """
    selection = None
    try:
        selection = MatchedCloudHandoff.model_validate(handoff)
        if selection.status != "ready":
            raise ValueError("cloud handoff is blocked")
    except (TypeError, ValueError, ContractError):
        outcome = MatchedExecutionReceipt(
            status="blocked",
            provider_invocation_count=0,
            judge_invocation_count=0,
            elapsed_seconds=0.0,
            blocker=PackageSafetyBlocker(
                code="invalid_matched_execution", message="Cloud execution requires a qualifying local handoff."
            ),
        )
    else:
        outcome = await execute_matched_lane(selection.cloud_plan, "cloud", calibrations, executions)
    return MatchedCloudExecutionReceipt(
        handoff=selection,
        handoff_sha256=None if selection is None else canonical_json_sha256(selection.model_dump(mode="json")),
        execution=outcome,
        status=outcome.status,
    )
