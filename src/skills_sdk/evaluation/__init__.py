"""Portable, non-executing evaluation services."""

from skills_sdk.evaluation.deterministic import evaluate_scenario_set
from skills_sdk.evaluation.deterministic_v2 import evaluate_scenario_set_v2

__all__ = ["evaluate_scenario_set", "evaluate_scenario_set_v2"]
