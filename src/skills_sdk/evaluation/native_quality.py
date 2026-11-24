"""Read-only native receipt assessment; no provider or judge is invoked."""

from __future__ import annotations

from skills_sdk.evaluation.scorer_calibration import _metrics
from skills_sdk.models.native_quality import (
    NativeLocalCheckRequest,
    NativeScorerCalibrationReceipt,
    native_calibration_matrix,
    require_native_declaration,
)
from skills_sdk.models.observed_calibration import NativeCalibrationReceipt
from skills_sdk.models.scenario_quality import ScenarioQualityFinding
from skills_sdk.models.scorer_quality import ScorerQualityReceipt


def assess_native_calibration(
    request: NativeLocalCheckRequest, declaration: ScorerQualityReceipt, observation: object
) -> NativeScorerCalibrationReceipt:
    """Join exact expected plan and declaration; reject stale, partial or failed evidence."""
    plan = request.calibration_plan
    findings: list[ScenarioQualityFinding] = []
    retained = None
    try:
        retained = NativeCalibrationReceipt.model_validate(observation)
        if retained.status != "pass" or retained.plan != plan:
            raise ValueError("native observation differs from the frozen passing plan")
        require_native_declaration(plan, declaration)
    except (ValueError, TypeError, RecursionError):
        findings.append(
            ScenarioQualityFinding(
                code="native_calibration_join_invalid",
                message="Native calibration requires complete evidence matching the frozen plan and scorer.",
                evidence_refs=("references/evals.yaml",),
            )
        )
    values: dict[str, object] = {
        "candidate": request.candidate,
        "status": "blocked" if findings else "pass",
        "findings": tuple(findings),
        "observation": retained,
    }
    if not findings and retained is not None:
        values.update(
            scorer_id=plan.scorer.scorer_id,
            scorer_version_or_digest=plan.scorer.version_or_digest,
            prompt_version=plan.assertion_contract_sha256,
            parameters=plan.parameters,
            example_count=len(retained.results),
            effective_policy=plan.policy,
            confusion_matrix=native_calibration_matrix(retained),
            metrics=_metrics(native_calibration_matrix(retained)),
        )
    return NativeScorerCalibrationReceipt.model_validate(values)
