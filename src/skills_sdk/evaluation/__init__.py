"""Portable, non-executing evaluation services."""

from skills_sdk.evaluation.deterministic import evaluate_scenario_set
from skills_sdk.evaluation.deterministic_v2 import evaluate_scenario_set_v2

__all__ = ["ScenarioQualityPolicy", "assess_scenario_quality", "evaluate_scenario_set", "evaluate_scenario_set_v2"]


def __getattr__(name: str) -> object:
    if name in {"ScenarioQualityPolicy", "assess_scenario_quality"}:
        from skills_sdk.evaluation.quality import ScenarioQualityPolicy, assess_scenario_quality

        return {
            "ScenarioQualityPolicy": ScenarioQualityPolicy,
            "assess_scenario_quality": assess_scenario_quality,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
