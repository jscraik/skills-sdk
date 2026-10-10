"""Portable, non-executing evaluation services."""

from skills_sdk.evaluation.deterministic import evaluate_scenario_set
from skills_sdk.evaluation.deterministic_v2 import evaluate_scenario_set_v2

__all__ = [
    "CalibrationProbeExecution",
    "CalibrationTrialAdapters",
    "ContentReviewDocument",
    "ContentReviewInput",
    "DimensionalJudgeAdapter",
    "DimensionalJudgeInput",
    "MatchedCaseExecution",
    "MatchedCompleteProviderAdapter",
    "MatchedProviderAdapter",
    "MatchedStreamingProviderAdapter",
    "MatchedTrialAdapters",
    "MatchedVariantExecution",
    "OfflineContentReviewAdapter",
    "PluginExecutionContext",
    "ScenarioQualityPolicy",
    "SelectedCaseDefinition",
    "SelectedCaseExecutionInput",
    "SelectedCaseJudgeAdapter",
    "SelectedCaseJudgeInput",
    "SuppliedTextProviderAdapter",
    "assess_matched_pair",
    "assess_plugin_pre_execution_safety",
    "assess_pre_execution_safety",
    "assess_scenario_coverage",
    "assess_scenario_quality",
    "assess_scorer_calibration",
    "assess_scorer_quality",
    "check_local_quality",
    "evaluate_scenario_set",
    "evaluate_scenario_set_v2",
    "execute_content_review",
    "execute_matched_calibration",
    "execute_matched_cloud",
    "execute_matched_cloud_regression",
    "execute_matched_lane",
    "execute_matched_regression",
    "execute_scorer_calibration",
    "execute_selected_case",
    "execute_selected_case_with_judge",
    "load_selected_case",
    "prepare_matched_cloud_handoff",
    "prepare_matched_plugin_context",
    "prepare_selected_case_context",
    "screen_plugin_security",
]


def __getattr__(name: str) -> object:
    """Load optional evaluation services only when requested."""
    if name in {"PluginExecutionContext", "prepare_matched_plugin_context"}:
        from skills_sdk.evaluation import matched_plugin_context

        return getattr(matched_plugin_context, name)
    if name in {"assess_plugin_pre_execution_safety", "screen_plugin_security"}:
        from skills_sdk.evaluation import plugin_safety

        return getattr(plugin_safety, name)
    if name in {
        "MatchedCaseExecution",
        "MatchedVariantExecution",
        "MatchedCompleteProviderAdapter",
        "MatchedStreamingProviderAdapter",
        "MatchedProviderAdapter",
        "MatchedTrialAdapters",
    }:
        from skills_sdk.evaluation import matched_admission

        return getattr(matched_admission, name)
    if name in {"DimensionalJudgeAdapter", "DimensionalJudgeInput", "execute_matched_calibration"}:
        from skills_sdk.evaluation import matched_calibration

        return getattr(matched_calibration, name)
    if name in {"execute_matched_cloud", "prepare_matched_cloud_handoff"}:
        from skills_sdk.evaluation import matched_handoff

        return getattr(matched_handoff, name)
    if name in {"execute_matched_regression", "execute_matched_cloud_regression"}:
        from skills_sdk.evaluation import matched_feedback

        return getattr(matched_feedback, name)
    if name == "execute_matched_lane":
        from skills_sdk.evaluation.matched_execution import execute_matched_lane

        return execute_matched_lane
    if name == "assess_matched_pair":
        from skills_sdk.evaluation.matched_comparison import assess_matched_pair

        return assess_matched_pair
    if name == "prepare_selected_case_context":
        from skills_sdk.evaluation.skill_context import prepare_selected_case_context

        return prepare_selected_case_context
    if name in {"CalibrationProbeExecution", "CalibrationTrialAdapters", "execute_scorer_calibration"}:
        from skills_sdk.evaluation import observed_calibration

        return getattr(observed_calibration, name)
    if name == "check_local_quality":
        from skills_sdk.evaluation.quality_workflow import check_local_quality

        return check_local_quality
    if name in {"assess_pre_execution_safety", "SelectedCaseExecutionInput"}:
        from skills_sdk.evaluation import pre_execution_safety

        return getattr(pre_execution_safety, name)
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
