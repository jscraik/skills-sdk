"""Portable, non-executing evaluation services."""

from skills_sdk.evaluation.deterministic import evaluate_scenario_set
from skills_sdk.evaluation.deterministic_v2 import evaluate_scenario_set_v2

__all__ = [
    "ScenarioQualityPolicy",
    "SelectedCaseDefinition",
    "SuppliedTextProviderAdapter",
    "assess_scenario_quality",
    "evaluate_scenario_set",
    "evaluate_scenario_set_v2",
    "execute_selected_case",
    "load_selected_case",
]


def __getattr__(name: str) -> object:
    """Load optional evaluation services only when requested."""
    if name in {"ScenarioQualityPolicy", "assess_scenario_quality"}:
        from skills_sdk.evaluation.quality import ScenarioQualityPolicy, assess_scenario_quality

        return {
            "ScenarioQualityPolicy": ScenarioQualityPolicy,
            "assess_scenario_quality": assess_scenario_quality,
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
