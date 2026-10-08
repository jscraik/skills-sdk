"""Portable, non-executing evaluation services."""

from skills_sdk.evaluation.deterministic import evaluate_scenario_set
from skills_sdk.evaluation.deterministic_v2 import evaluate_scenario_set_v2

__all__ = [
    "ContentReviewDocument",
    "ContentReviewInput",
    "OfflineContentReviewAdapter",
    "ScenarioQualityPolicy",
    "SelectedCaseDefinition",
    "SelectedCaseJudgeAdapter",
    "SelectedCaseJudgeInput",
    "SuppliedTextProviderAdapter",
    "assess_scenario_coverage",
    "assess_scenario_quality",
    "assess_scorer_calibration",
    "assess_scorer_quality",
    "check_local_quality",
    "evaluate_scenario_set",
    "evaluate_scenario_set_v2",
    "execute_content_review",
    "execute_selected_case",
    "execute_selected_case_with_judge",
    "load_selected_case",
]


def __getattr__(name: str) -> object:
    """Load optional evaluation services only when requested."""
    if name == "check_local_quality":
        from skills_sdk.evaluation.quality_workflow import check_local_quality

        return check_local_quality
    if name in {"ContentReviewDocument", "ContentReviewInput", "OfflineContentReviewAdapter", "execute_content_review"}:
        from skills_sdk.evaluation import content_review

        return getattr(content_review, name)
    if name == "assess_scenario_coverage":
        from skills_sdk.evaluation.coverage import assess_scenario_coverage

        return assess_scenario_coverage
    if name in {"ScenarioQualityPolicy", "assess_scenario_quality"}:
        from skills_sdk.evaluation.quality import ScenarioQualityPolicy, assess_scenario_quality

        return {
            "ScenarioQualityPolicy": ScenarioQualityPolicy,
            "assess_scenario_quality": assess_scenario_quality,
        }[name]
    if name == "assess_scorer_quality":
        from skills_sdk.evaluation.scorer_quality import assess_scorer_quality

        return assess_scorer_quality
    if name == "assess_scorer_calibration":
        from skills_sdk.evaluation.scorer_calibration import assess_scorer_calibration

        return assess_scorer_calibration
    if name in {
        "SelectedCaseJudgeAdapter",
        "SelectedCaseJudgeInput",
        "execute_selected_case_with_judge",
    }:
        from skills_sdk.evaluation.live_selected_case import (
            SelectedCaseJudgeAdapter,
            SelectedCaseJudgeInput,
            execute_selected_case_with_judge,
        )

        return {
            "SelectedCaseJudgeAdapter": SelectedCaseJudgeAdapter,
            "SelectedCaseJudgeInput": SelectedCaseJudgeInput,
            "execute_selected_case_with_judge": execute_selected_case_with_judge,
        }[name]
    if name in {
        "SelectedCaseDefinition",
        "SuppliedTextProviderAdapter",
        "execute_selected_case",
        "load_selected_case",
    }:
        from skills_sdk.evaluation.selected_case import (
            SelectedCaseDefinition,
            SuppliedTextProviderAdapter,
            execute_selected_case,
            load_selected_case,
        )

        return {
            "SelectedCaseDefinition": SelectedCaseDefinition,
            "SuppliedTextProviderAdapter": SuppliedTextProviderAdapter,
            "execute_selected_case": execute_selected_case,
            "load_selected_case": load_selected_case,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
