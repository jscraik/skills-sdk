from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.scenario_quality import ScenarioQualityAppliedPolicyV2, ScenarioQualityReceiptV2


def test_v2_policy_requires_every_field_on_wire() -> None:
    policy = {
        "minimum_release_cases": 10,
        "target_release_cases": 10,
        "maximum_release_cases": 10,
        "minimum_pressure_or_regression": 1,
        "minimum_negative_or_edge": 1,
    }
    receipt = ScenarioQualityReceiptV2(
        scope="all",
        status="blocked",
        scenario_count=0,
        effective_policy=ScenarioQualityAppliedPolicyV2.model_validate(policy),
        findings=({"code": "missing_evals_yaml", "message": "No evaluation file."},),
    ).model_dump(mode="json")
    registry = SchemaRegistry()
    registry.validate("scenario-quality.v2", receipt)
    validator = Draft202012Validator(registry.load("scenario-quality.v2"))

    for omitted_field in (None, *policy):
        invalid_policy = (
            {} if omitted_field is None else {key: value for key, value in policy.items() if key != omitted_field}
        )
        invalid_receipt = {**receipt, "effective_policy": invalid_policy}
        with pytest.raises(ValidationError):
            ScenarioQualityAppliedPolicyV2.model_validate(invalid_policy)
        with pytest.raises(ValidationError):
            ScenarioQualityReceiptV2.model_validate(invalid_receipt)
        assert list(validator.iter_errors(invalid_receipt))
        with pytest.raises(ContractError):
            registry.validate("scenario-quality.v2", invalid_receipt)
