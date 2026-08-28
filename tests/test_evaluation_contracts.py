from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.evaluation import ScenarioSet, ScorerProfile

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "evaluation"


def test_release_scenario_fixture_requires_regression_coverage() -> None:
    payload = json.loads((FIXTURE_ROOT / "scenario-accepted.json").read_text(encoding="utf-8"))
    scenario_set = ScenarioSet.model_validate(payload)
    assert scenario_set.release is True
    assert {case.category for case in scenario_set.cases} == {"happy", "boundary", "regression"}


def test_release_scenario_without_regression_is_rejected() -> None:
    payload = json.loads((FIXTURE_ROOT / "scenario-accepted.json").read_text(encoding="utf-8"))
    payload["cases"] = [case for case in payload["cases"] if case["category"] != "regression"]
    with pytest.raises(ValidationError, match="regression case"):
        ScenarioSet.model_validate(payload)


def test_scorer_fixture_requires_deterministic_first() -> None:
    payload = json.loads((FIXTURE_ROOT / "scorer-accepted.json").read_text(encoding="utf-8"))
    scorer = ScorerProfile.model_validate(payload)
    assert scorer.calibration_required is True
    assert scorer.deterministic_checks_first is True


def test_external_scorer_without_calibration_is_rejected() -> None:
    payload = json.loads((FIXTURE_ROOT / "scorer-accepted.json").read_text(encoding="utf-8"))
    payload["calibration_probe_ids"] = []
    with pytest.raises(ValidationError, match="calibration probes"):
        ScorerProfile.model_validate(payload)


def test_opaque_scorer_cannot_opt_out_of_calibration() -> None:
    payload = json.loads((FIXTURE_ROOT / "scorer-accepted.json").read_text(encoding="utf-8"))
    payload["calibration_required"] = False
    with pytest.raises(ValidationError, match="require calibration"):
        ScorerProfile.model_validate(payload)


def test_duplicate_scenario_ids_are_rejected() -> None:
    payload = json.loads((FIXTURE_ROOT / "scenario-accepted.json").read_text(encoding="utf-8"))
    payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]
    with pytest.raises(ValidationError, match="case ids"):
        ScenarioSet.model_validate(payload)


def test_scenario_schema_requires_regression_for_release() -> None:
    payload = json.loads((FIXTURE_ROOT / "scenario-accepted.json").read_text(encoding="utf-8"))
    payload["cases"] = [case for case in payload["cases"] if case["category"] != "regression"]
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("scenario-set.v1", payload)


def test_scenario_registry_rejects_duplicate_nested_case_ids() -> None:
    payload = json.loads((FIXTURE_ROOT / "scenario-accepted.json").read_text(encoding="utf-8"))
    payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]
    with pytest.raises(ContractError, match="contract_validation_failed") as error:
        SchemaRegistry().validate("scenario-set.v1", payload)
    assert any("case ids" in detail for detail in error.value.details)


def test_scorer_schema_requires_calibration_probes() -> None:
    payload = json.loads((FIXTURE_ROOT / "scorer-accepted.json").read_text(encoding="utf-8"))
    payload["calibration_probe_ids"] = []
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("scorer-profile.v1", payload)


def test_scorer_schema_rejects_duplicate_calibration_probes() -> None:
    payload = json.loads((FIXTURE_ROOT / "scorer-accepted.json").read_text(encoding="utf-8"))
    payload["calibration_probe_ids"].append(payload["calibration_probe_ids"][0])
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("scorer-profile.v1", payload)


def test_scorer_schema_rejects_opaque_calibration_opt_out() -> None:
    payload = json.loads((FIXTURE_ROOT / "scorer-accepted.json").read_text(encoding="utf-8"))
    payload["calibration_required"] = False
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("scorer-profile.v1", payload)


@pytest.mark.parametrize(
    ("schema_name", "fixture_name", "field_path"),
    [
        ("scenario-set.v1", "scenario-accepted.json", ("scenario_set_id",)),
        ("scenario-set.v1", "scenario-accepted.json", ("cases", 0, "prompt")),
        ("scorer-profile.v1", "scorer-accepted.json", ("scorer_id",)),
    ],
)
def test_evaluation_schemas_reject_whitespace_only_text(
    schema_name: str, fixture_name: str, field_path: tuple[str | int, ...]
) -> None:
    payload = json.loads((FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"))
    target: Any = payload
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = "   "
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate(schema_name, payload)
