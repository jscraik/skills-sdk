"""Candidate-bound composition of existing local quality services."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from skills_sdk.evaluation.content_review import OfflineContentReviewAdapter, execute_content_review
from skills_sdk.evaluation.coverage import assess_scenario_coverage
from skills_sdk.evaluation.scorer_calibration import assess_scorer_calibration
from skills_sdk.evaluation.scorer_quality import assess_scorer_quality
from skills_sdk.intake import intake_skill_package
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.quality_workflow import (
    LocalCheckRequestV2,
    LocalCheckResultV2,
    LocalQualityStage,
    QualityStageName,
    QualityStageReceipt,
)
from skills_sdk.validation import SkillValidationPolicy, validate_skill_package
from skills_sdk.validation.content_review import assess_content_review


def _blocked(
    request: LocalCheckRequestV2 | None, stages: list[LocalQualityStage], stage: str, code: str
) -> LocalCheckResultV2:
    """Return portable orchestration failure without host paths or exception text."""
    return LocalCheckResultV2(
        status="blocked",
        request=request,
        applied_policy=request.policy
        if request is not None and any(item.name == "intake" for item in stages)
        else None,
        stages=tuple(stages),
        blocked_stage=stage,
        blocker=PackageReceiptBlocker(code=code, message="Local quality workflow stopped at the reported stage."),
    )


def _record(
    request: LocalCheckRequestV2, stages: list[LocalQualityStage], name: QualityStageName, receipt: QualityStageReceipt
) -> LocalCheckResultV2 | None:
    """Stop at the first changed candidate or incomplete stage; retain its receipt."""
    stage = LocalQualityStage(name=name, receipt=receipt)
    stages.append(stage)
    candidate = request.update_baseline if name == "baseline" else request.candidate
    if receipt.candidate != candidate:
        return _blocked(request, stages, "candidate_changed", "quality_candidate_changed")
    if not stage.passed():
        return _blocked(request, stages, name, "quality_stage_incomplete")
    return None


def _deterministic_stages(
    root: Path, request: LocalCheckRequestV2, policy: SkillValidationPolicy
) -> Iterator[tuple[QualityStageName, QualityStageReceipt]]:
    """Yield actual receipts lazily so no downstream check runs after a blocker."""
    revision = request.candidate.source_revision
    yield "intake", intake_skill_package(root, request.intake, policy=policy)
    yield "validate", validate_skill_package(root, source_revision=revision, policy=policy)
    yield (
        "scenario-coverage",
        assess_scenario_coverage(
            root,
            source_revision=revision,
            scenario_set_id=request.coverage_plan.scenario_set_id,
            coverage_plan=request.coverage_plan,
        ),
    )
    yield "scorer-quality", assess_scorer_quality(root, source_revision=revision)
    yield "scorer-calibration", assess_scorer_calibration(root, source_revision=revision)


def _final_result(
    root: Path, request: LocalCheckRequestV2, stages: list[LocalQualityStage], baseline_root: Path | None
) -> LocalCheckResultV2:
    """Capture both current and baseline source after every quality stage has passed."""
    policy = SkillValidationPolicy(**request.policy.model_dump())
    current = validate_skill_package(root, source_revision=request.candidate.source_revision, policy=policy)
    baseline = None
    if request.update_baseline is not None and baseline_root is not None:
        baseline = validate_skill_package(baseline_root, source_revision=request.update_baseline.source_revision)
    unchanged = current.status == "pass" and current.candidate == request.candidate
    if request.update_baseline is not None:
        unchanged = (
            unchanged
            and baseline is not None
            and baseline.status == "pass"
            and baseline.candidate == request.update_baseline
        )
    return LocalCheckResultV2(
        status="local_checks_passed" if unchanged else "blocked",
        request=request,
        applied_policy=request.policy,
        stages=tuple(stages),
        final_capture=current,
        baseline_final_capture=baseline,
        blocked_stage=None if unchanged else "final-capture",
        blocker=None
        if unchanged
        else PackageReceiptBlocker(
            code="quality_final_capture_changed", message="Final source capture failed or changed candidate identity."
        ),
    )


async def check_local_quality(
    package_root: Path,
    request: object,
    *,
    baseline_root: Path | None = None,
    assessment: object = None,
    adapter: OfflineContentReviewAdapter | None = None,
) -> LocalCheckResultV2:
    """Check local quality without running scenarios, judges, or promotion adapters.

    Supplied content is assessed read-only. Observed content invokes only the
    explicitly provided trusted callback; its receipt is a separate evidence lane.
    """
    try:
        selected = LocalCheckRequestV2.model_validate(request)
    except (ValidationError, ValueError, TypeError, RecursionError):
        return _blocked(None, [], "request", "invalid_quality_request")
    stages: list[LocalQualityStage] = []
    if selected.intent == "update":
        if baseline_root is None:
            return _blocked(selected, stages, "baseline", "quality_input_missing")
        baseline = validate_skill_package(baseline_root, source_revision=selected.update_baseline.source_revision)
        stopped = _record(selected, stages, "baseline", baseline)
        if stopped is not None:
            return stopped
    elif baseline_root is not None:
        return _blocked(None, [], "request", "unexpected_quality_baseline")
    policy = SkillValidationPolicy(**selected.policy.model_dump())
    for name, receipt in _deterministic_stages(package_root, selected, policy):
        stopped = _record(selected, stages, name, receipt)
        if stopped is not None:
            return stopped
    if selected.content_review_mode == "observed":
        if adapter is None or assessment is not None:
            return _blocked(selected, stages, "content-review", "quality_input_missing")
        content = await execute_content_review(
            package_root, source_revision=selected.candidate.source_revision, adapter=adapter
        )
    else:
        if adapter is not None:
            return _blocked(selected, stages, "content-review", "quality_input_missing")
        content = assess_content_review(
            package_root, source_revision=selected.candidate.source_revision, assessment=assessment
        )
    stopped = _record(selected, stages, "content-review", content)
    return stopped if stopped is not None else _final_result(package_root, selected, stages, baseline_root)


__all__ = ["check_local_quality"]
