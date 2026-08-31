"""Small grouped imports for generated schema model families."""

from __future__ import annotations

from typing import Any

from skills_sdk.models.evaluation import (
    EvaluationReceipt,
    ScenarioCaseResult,
    ScenarioObservation,
    ScenarioSet,
    ScorerProfile,
)
from skills_sdk.models.evaluation_v2 import (
    EvaluationReceiptV2,
    ScenarioCaseResultV2,
    ScenarioObservationV2,
    ScenarioSetV2,
)
from skills_sdk.models.provider_execution import ProviderExecutionRequest, ProviderExecutionResult


def evaluation_schema_models() -> tuple[tuple[type[Any], str], ...]:
    """Return stable evaluation schema registrations in generation order."""

    return (
        (ScenarioSet, "scenario-set.v1.schema.json"),
        (ScorerProfile, "scorer-profile.v1.schema.json"),
        (ScenarioObservation, "scenario-observation.v1.schema.json"),
        (ScenarioCaseResult, "scenario-case-result.v1.schema.json"),
        (EvaluationReceipt, "evaluation-receipt.v1.schema.json"),
        (ScenarioSetV2, "scenario-set.v2.schema.json"),
        (ScenarioObservationV2, "scenario-observation.v2.schema.json"),
        (ScenarioCaseResultV2, "scenario-case-result.v2.schema.json"),
        (EvaluationReceiptV2, "evaluation-receipt.v2.schema.json"),
    )


def provider_execution_schema_models() -> tuple[tuple[type[Any], str], ...]:
    """Return provider execution schemas in request-before-result order."""

    return (
        (ProviderExecutionRequest, "provider-execution-request.v1.schema.json"),
        (ProviderExecutionResult, "provider-execution-result.v1.schema.json"),
    )


__all__ = ["evaluation_schema_models", "provider_execution_schema_models"]
